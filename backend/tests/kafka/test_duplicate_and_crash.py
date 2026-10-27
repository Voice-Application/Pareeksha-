"""T-NFR-4: duplicates and crashes give exactly one evaluation (and one downstream note).

Real Kafka, the Alembic-built database, handlers that write the real ``evaluations`` table with a
plain INSERT (a second run would violate the unique key), and real processes killed with SIGKILL.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from pareeksha.events.consumer import Ctx, Outgoing, RetryableError
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
from tests.kafka.kit import (
    FAST,
    call_completed,
    consumer,
    evaluate,
    evaluate_again,
    evaluation_count,
    lag_is_zero,
    prepare_notes_table,
    prime_group,
    publish_once,
    read_topic,
    scalar,
    seed_calls,
    settings_for,
    spec_for,
    unique,
    wait_for,
    write_note,
)

BACKEND = Path(__file__).resolve().parents[2]
IN, OUT = Topics.CALL_COMPLETED, Topics.EVALUATION_COMPLETED


@pytest.fixture
def settings(database_url: str) -> EventSettings:
    s = settings_for(database_url)
    prepare_notes_table(s)
    return s


def processed(settings: EventSettings, group: str, event_id: uuid.UUID) -> int:
    return int(
        scalar(
            settings,
            "SELECT count(*) FROM processed_events WHERE consumer_group = %s AND event_id = %s",
            group,
            event_id,
        )
    )


async def output_ids(call_id: uuid.UUID) -> set[str]:
    return {json.loads(m.value)["event_id"] for m in await read_topic(OUT, key=str(call_id))}


async def test_duplicate_deliveries_give_one_evaluation_and_one_output_id(
    settings: EventSettings,
) -> None:
    [call_id] = seed_calls(settings)
    group = unique("dup")
    env = call_completed(call_id)
    async with consumer(settings, spec_for(group, IN, evaluate, evaluate_again)) as c:
        for _ in range(4):  # the broker (or a producer retry) delivers the same event 4 times
            await c.send(env)

        async def all_outputs() -> bool:
            return len(await read_topic(OUT, key=str(call_id))) >= 4

        await wait_for(all_outputs, what="output for every delivery")
        await wait_for(lambda: lag_is_zero(group, [IN]), what="zero lag")
    assert evaluation_count(settings, call_id) == 1
    assert processed(settings, group, env.event_id) == 1
    assert await output_ids(call_id) == {str(uuid.uuid5(env.event_id, "evaluation.completed"))}


class Worker:
    """A consumer subprocess (``tests.kafka.crash_worker``) the test can kill."""

    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc
        self.lines: list[str] = []

    @classmethod
    async def spawn(cls, settings: EventSettings, group: str, mode: str) -> Worker:
        env = {**os.environ, "QA_DATABASE_URL": settings.database_url, "PYTHONUNBUFFERED": "1"}
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tests.kafka.crash_worker",
            group,
            mode,
            cwd=BACKEND,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        return cls(proc)

    async def wait_for_line(self, prefix: str, timeout: float = 60.0) -> str:
        assert self.proc.stdout is not None
        stream = self.proc.stdout

        async def read() -> str:
            while True:
                raw = await stream.readline()
                if not raw:
                    raise AssertionError(f"worker exited before {prefix!r}: {self.lines[-5:]}")
                line = raw.decode().rstrip()
                self.lines.append(line)
                if line.startswith(prefix):
                    return line

        return await asyncio.wait_for(read(), timeout)

    async def drain(self) -> None:
        assert self.proc.stdout is not None
        self.lines += (await self.proc.stdout.read()).decode().splitlines()

    async def stop(self) -> int:
        if self.proc.returncode is None:
            self.proc.send_signal(signal.SIGTERM)
        code = await asyncio.wait_for(self.proc.wait(), 30)
        await self.drain()
        return code


async def test_kill_9_inside_the_handler_loses_nothing_and_duplicates_nothing(
    settings: EventSettings,
) -> None:
    [call_id] = seed_calls(settings)
    group = unique("crash")
    env = call_completed(call_id)
    await prime_group(group, [IN])
    await publish_once(settings, env)

    doomed = await Worker.spawn(settings, group, "crash_in_handler")
    await doomed.wait_for_line("HANDLER")
    assert await asyncio.wait_for(doomed.proc.wait(), 30) == -signal.SIGKILL
    assert evaluation_count(settings, call_id) == 0  # the open transaction died with the process
    assert processed(settings, group, env.event_id) == 0
    assert not await lag_is_zero(group, [IN])  # the offset was never committed

    survivor = await Worker.spawn(settings, group, "normal")
    await survivor.wait_for_line("READY")

    async def done() -> bool:
        return evaluation_count(settings, call_id) == 1 and await lag_is_zero(group, [IN])

    await wait_for(done, what="the next group member handles the redelivered message")
    assert await survivor.stop() == 0
    assert [ln for ln in survivor.lines if ln.startswith("HANDLER")] == [f"HANDLER {env.event_id}"]
    assert evaluation_count(settings, call_id) == 1
    assert processed(settings, group, env.event_id) == 1
    assert await output_ids(call_id) == {str(uuid.uuid5(env.event_id, "evaluation.completed"))}


async def test_kill_9_after_the_commit_but_before_the_offset_does_not_run_the_handler_twice(
    settings: EventSettings,
) -> None:
    [call_id] = seed_calls(settings)
    group = unique("crash2")
    env = call_completed(call_id)
    await prime_group(group, [IN])
    await publish_once(settings, env)

    doomed = await Worker.spawn(settings, group, "crash_before_produce")
    await doomed.wait_for_line("ABOUT_TO_PRODUCE")
    assert await asyncio.wait_for(doomed.proc.wait(), 30) == -signal.SIGKILL
    assert evaluation_count(settings, call_id) == 1  # committed before the crash
    assert await output_ids(call_id) == set()  # but nothing was produced
    assert not await lag_is_zero(group, [IN])

    survivor = await Worker.spawn(settings, group, "normal")

    async def produced() -> bool:
        return bool(await output_ids(call_id)) and await lag_is_zero(group, [IN])

    await wait_for(produced, what="duplicate detected, output re-produced, offset committed")
    assert await survivor.stop() == 0
    assert [ln for ln in survivor.lines if ln.startswith("HANDLER")] == []  # handler not re-run
    assert [ln for ln in survivor.lines if ln.startswith("REPRODUCE")] == [
        f"REPRODUCE {env.event_id}"
    ]
    assert evaluation_count(settings, call_id) == 1
    assert await output_ids(call_id) == {str(uuid.uuid5(env.event_id, "evaluation.completed"))}


async def test_chain_with_duplicates_and_a_failing_sink_ends_with_one_note_per_call(
    settings: EventSettings,
) -> None:
    calls = seed_calls(settings, 5)
    ev_group, note_group = unique("chain-eval"), unique("chain-note")
    failed_once: set[uuid.UUID] = set()

    async def flaky_note(env: Any, ctx: Ctx) -> Sequence[Outgoing]:
        if env.payload.call_id not in failed_once:  # the CRM answers 503 the first time
            failed_once.add(env.payload.call_id)
            raise RetryableError("crm 503")
        return await write_note(env, ctx)

    note_spec = spec_for(note_group, OUT, flaky_note)
    async with consumer(settings, note_spec, policy=FAST, with_retry_path=True) as notes:
        async with consumer(settings, spec_for(ev_group, IN, evaluate, evaluate_again)) as ev:
            for call_id in calls:
                env = call_completed(call_id)
                for _ in range(3):
                    await ev.send(env)

            async def finished() -> bool:
                have = scalar(
                    settings, "SELECT count(*) FROM qa_crm_notes WHERE call_id = ANY(%s)", calls
                )
                return have == 5 and await lag_is_zero(note_group, [OUT])

            await wait_for(finished, timeout=60, what="one note per call")
            await wait_for(lambda: lag_is_zero(ev_group, [IN]), what="evaluator lag zero")
            assert notes.retrier_group is not None
            await wait_for(
                lambda: lag_is_zero(notes.retrier_group, [Topics.RETRY_30S, Topics.RETRY_5M]),
                what="retrier lag zero",
            )
    for call_id in calls:
        assert evaluation_count(settings, call_id) == 1
        assert (
            scalar(settings, "SELECT count(*) FROM qa_crm_notes WHERE call_id = %s", call_id) == 1
        )
    assert failed_once == set(calls)  # every call really took the retry path
    dead = scalar(
        settings,
        "SELECT count(*) FROM dead_letters WHERE consumer_group = ANY(%s)",
        [ev_group, note_group],
    )
    assert dead == 0
