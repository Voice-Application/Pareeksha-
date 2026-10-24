"""Crash recovery with real processes: SIGKILL a consumer and start another in the same group.

``crash_in_handler``: killed before the DB transaction commits -> nothing persisted, offset
uncommitted -> the next member is redelivered the message and handles it exactly once.
``crash_before_produce``: killed after the DB commit but before the output is produced and before
the offset commit -> the next member sees a duplicate, skips the handler, re-produces the output
(deterministic event_id) and commits the offset.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import uuid
from pathlib import Path

from pareeksha.events.producer import EventProducer
from pareeksha.events.topics import Topics
from tests.integration.support import (
    SETTINGS,
    TEST_DB_URL,
    audit_envelope,
    db,
    group_lag,
    prime_group,
    read_topic,
    side_effects,
    unique_group,
    wait_for,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
AUDIT = Topics.AUDIT_REQUESTED


class Worker:
    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc
        self.lines: list[str] = []

    @classmethod
    async def spawn(cls, group: str, mode: str) -> Worker:
        env = {**os.environ, "INFRA_TEST_DATABASE_URL": TEST_DB_URL, "PYTHONUNBUFFERED": "1"}
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tests.integration.crash_worker",
            group,
            mode,
            cwd=BACKEND_DIR,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        return cls(proc)

    async def wait_for_line(self, prefix: str, timeout: float = 60.0) -> str:
        assert self.proc.stdout is not None

        async def read() -> str:
            while True:
                raw = await self.proc.stdout.readline()  # type: ignore[union-attr]
                if not raw:
                    raise AssertionError(f"worker exited before printing {prefix!r}: {self.lines}")
                line = raw.decode().rstrip()
                self.lines.append(line)
                if line.startswith(prefix):
                    return line

        return await asyncio.wait_for(read(), timeout)

    async def drain(self) -> None:
        assert self.proc.stdout is not None
        rest = await self.proc.stdout.read()
        self.lines += rest.decode().splitlines()


def _processed(group: str, event_id: uuid.UUID) -> int:
    with db() as conn:
        row = conn.execute(
            "SELECT count(*) FROM processed_events WHERE consumer_group = %s AND event_id = %s",
            (group, event_id),
        ).fetchone()
    assert row is not None
    return int(row[0])


async def _lag(group: str) -> int:
    return sum((await group_lag(group, [AUDIT])).values())


async def _stop_gracefully(worker: Worker) -> None:
    worker.proc.send_signal(signal.SIGTERM)
    assert await asyncio.wait_for(worker.proc.wait(), 30) == 0, "SIGTERM must exit cleanly"
    await worker.drain()


async def test_kill_9_mid_handler_redelivers_and_processes_once() -> None:
    group = unique_group("crash-handler")
    env = audit_envelope()
    await prime_group(group, [AUDIT])

    victim = await Worker.spawn(group, "crash_in_handler")
    await victim.wait_for_line("READY")
    producer = EventProducer(SETTINGS.bootstrap_servers)
    await producer.start()
    try:
        await producer.publish(env)
    finally:
        await producer.stop()
    await victim.wait_for_line("HANDLER")
    assert await asyncio.wait_for(victim.proc.wait(), 30) == -signal.SIGKILL

    # nothing survived the crash: no side effect, no idempotency row, offset still uncommitted
    assert side_effects(group, env.event_id) == 0
    assert _processed(group, env.event_id) == 0
    assert await _lag(group) == 1

    survivor = await Worker.spawn(group, "normal")
    await survivor.wait_for_line("READY")
    await survivor.wait_for_line(f"HANDLER {env.event_id}")

    async def committed() -> bool:
        return await _lag(group) == 0

    await wait_for(committed, what="offset committed after redelivery")
    await _stop_gracefully(survivor)

    assert side_effects(group, env.event_id) == 1
    assert _processed(group, env.event_id) == 1
    assert [ln for ln in survivor.lines if ln.startswith("HANDLER")] == [f"HANDLER {env.event_id}"]
    assert not any(ln.startswith("REPRODUCE") for ln in survivor.lines)
    outputs = await read_topic(Topics.CALL_COMPLETED, key=str(env.payload.call_id))
    assert [json.loads(o.value)["event_id"] for o in outputs] == [
        str(uuid.uuid5(env.event_id, "call.completed"))
    ]


async def test_kill_9_after_db_commit_reproduces_output_without_second_side_effect() -> None:
    group = unique_group("crash-produce")
    env = audit_envelope()
    await prime_group(group, [AUDIT])

    victim = await Worker.spawn(group, "crash_before_produce")
    await victim.wait_for_line("READY")
    producer = EventProducer(SETTINGS.bootstrap_servers)
    await producer.start()
    try:
        await producer.publish(env)
    finally:
        await producer.stop()
    await victim.wait_for_line("ABOUT_TO_PRODUCE")
    assert await asyncio.wait_for(victim.proc.wait(), 30) == -signal.SIGKILL

    # DB work is committed, but the offset is not and no output exists yet
    assert side_effects(group, env.event_id) == 1
    assert _processed(group, env.event_id) == 1
    assert await _lag(group) == 1
    assert await read_topic(Topics.CALL_COMPLETED, key=str(env.payload.call_id)) == []

    survivor = await Worker.spawn(group, "normal")
    await survivor.wait_for_line("READY")
    await survivor.wait_for_line(f"REPRODUCE {env.event_id}")

    async def committed() -> bool:
        return await _lag(group) == 0

    await wait_for(committed, what="offset committed after re-produce")
    await _stop_gracefully(survivor)

    assert side_effects(group, env.event_id) == 1, "the handler must not run a second time"
    assert not any(ln.startswith("HANDLER") for ln in survivor.lines)
    outputs = await read_topic(Topics.CALL_COMPLETED, key=str(env.payload.call_id))
    assert [json.loads(o.value)["event_id"] for o in outputs] == [
        str(uuid.uuid5(env.event_id, "call.completed"))
    ]
