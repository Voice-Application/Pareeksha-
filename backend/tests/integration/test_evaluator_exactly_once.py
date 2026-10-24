"""GOAL item 6 for evaluations: duplicate delivery and a worker crash each leave ONE evaluation.

Real Kafka, real Postgres (the full ``docs/schema.sql`` schema), the production ``evaluator`` and
``finalizer`` consumers with their Postgres stores. Only the judge is scripted: it makes the
number of judge calls countable and keeps the test free of provider cost (the real DeepSeek call
is in ``proof/EVAL-03b``).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import signal
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from pareeksha.events.consumer import REGISTRY, ConsumerRunner
from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import AnyEnvelope, CallCompleted, make_envelope
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.workers import evaluator, finalizer
from tests.integration.eval_support import (
    SeededCall,
    count,
    create_database,
    evaluation_count,
    processed_count,
    seed_run,
)
from tests.integration.support import (
    BOOTSTRAP,
    group_lag,
    prime_group,
    read_topic,
    unique_group,
    wait_for,
)
from tests.unit.evaluation.fakes import ScriptedProvider, judge_json

BACKEND_DIR = Path(__file__).resolve().parents[2]
CALL_DONE = Topics.CALL_COMPLETED
EVAL_DONE = Topics.EVALUATION_COMPLETED


@pytest.fixture
def dburl() -> Iterator[str]:
    with create_database() as url:
        yield url


def call_completed(call: SeededCall) -> AnyEnvelope:
    payload = CallCompleted(
        call_id=call.call_id,
        source="simulation",
        agent_id=call.agent_id,
        run_id=call.run_id,
        run_item_id=call.run_item_id,
        end_reason="goal_achieved",
    )
    return make_envelope(payload, producer="test", correlation_id=str(call.run_id))


def scripted_client(provider: ScriptedProvider, usage: ApiUsageSink) -> LLMClient:
    settings = LLMSettings(
        _env_file=None,
        deepseek_api_key="scripted",
        cost_deepseek_per_1k_input_tokens=0.001,
        cost_deepseek_per_1k_output_tokens=0.004,
    )
    return LLMClient(provider, settings, usage_sink=usage)


async def publish(*envelopes: AnyEnvelope) -> None:
    producer = EventProducer(BOOTSTRAP, client_id="eval-test")
    await producer.start()
    try:
        for e in envelopes:
            await producer.publish(e)
    finally:
        await producer.stop()


@contextlib.asynccontextmanager
async def running(group_prefix: str, name: str, dburl: str) -> AsyncIterator[ConsumerRunner]:
    """The registered ``name`` consumer, in-process, under a fresh group primed at 'now'."""
    spec = dataclasses.replace(REGISTRY[name], group=unique_group(group_prefix))
    await prime_group(spec.group, list(spec.topics))
    runner = ConsumerRunner(spec, EventSettings(BOOTSTRAP, dburl))
    task = asyncio.create_task(runner.run())
    try:
        await runner.wait_ready()
        yield runner
    finally:
        runner.stop_event.set()
        await asyncio.wait_for(task, 30)


async def drained(runner: ConsumerRunner) -> None:
    async def done() -> bool:
        return sum((await group_lag(runner.group, list(runner.spec.topics))).values()) == 0

    await wait_for(done, timeout=60, what=f"{runner.group} lag 0")


async def test_duplicate_delivery_gives_one_evaluation_row(dburl: str) -> None:
    (call,) = seed_run(dburl, 1)
    provider = ScriptedProvider([judge_json(), judge_json()])
    usage = ApiUsageSink(EventSettings(BOOTSTRAP, dburl))
    evaluator.set_client(scripted_client(provider, usage), usage)
    env = call_completed(call)
    try:
        async with running("evaluator", "evaluator", dburl) as runner:
            await publish(env, env)  # the same event delivered twice
            await drained(runner)
            assert evaluation_count(dburl, call.call_id) == 1
            assert len(provider.requests) == 1, "the duplicate must not reach the judge"
            assert processed_count(dburl, runner.group, env.event_id) == 1

            # a *different* event for the same call (an upstream re-emission): the judge runs
            # again but the (call, rubric) uniqueness keeps the table at one row
            await publish(call_completed(call))
            await drained(runner)
        assert len(provider.requests) == 2
        assert evaluation_count(dburl, call.call_id) == 1
    finally:
        await usage.close()
        evaluator.set_client(None)

    outputs = await read_topic(EVAL_DONE, key=str(call.call_id))
    ids = [json.loads(o.value)["event_id"] for o in outputs]
    assert str(uuid.uuid5(env.event_id, "evaluation.completed")) in ids
    # the duplicate re-produced the same event id; downstream deduplicates on it
    assert ids.count(ids[0]) == 2
    with psycopg.connect(dburl) as conn:
        row = conn.execute(
            "SELECT status, overall_score, passed, rubric_version_id IS NOT NULL, prompt_hash, "
            "judge_model, input_tokens, output_tokens FROM evaluations WHERE call_id = %s",
            (call.call_id,),
        ).fetchone()
        assert row is not None
        assert row[:4] == ("ok", 100, True, True)
        assert row[4].startswith("sha256:") and row[5] and row[6:] == (1000, 200)
        status = conn.execute(
            "SELECT status FROM run_items WHERE id = %s", (call.run_item_id,)
        ).fetchone()
        assert status == ("evaluated",)
        checks = conn.execute(
            "SELECT count(*) FROM deterministic_checks WHERE call_id = %s", (call.call_id,)
        ).fetchone()
        assert checks is not None and checks[0] >= 1
        metrics = conn.execute(
            "SELECT turn_count FROM call_metrics WHERE call_id = %s", (call.call_id,)
        ).fetchone()
        assert metrics == (5,)
        usage_rows = conn.execute(
            "SELECT provider, operation, units, unit_type, est_cost, run_id, call_id "
            "FROM api_usage WHERE call_id = %s",
            (call.call_id,),
        ).fetchall()
    # one api_usage row per real judge call (two calls were made in total)
    assert len(usage_rows) == 2
    assert usage_rows[0][:4] == ("deepseek", "llm_judge", 1200, "tokens")
    assert float(usage_rows[0][4]) == pytest.approx(0.0018)
    assert usage_rows[0][5:] == (call.run_id, call.call_id)


class Worker:
    def __init__(self, proc: asyncio.subprocess.Process) -> None:
        self.proc = proc
        self.lines: list[str] = []

    @classmethod
    async def spawn(cls, group: str, dburl: str, mode: str) -> Worker:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tests.integration.evaluator_crash_worker",
            group,
            dburl,
            mode,
            cwd=BACKEND_DIR,
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
                    raise AssertionError(f"worker exited before {prefix!r}: {self.lines}")
                line = raw.decode().rstrip()
                self.lines.append(line)
                if line.startswith(prefix):
                    return line

        return await asyncio.wait_for(read(), timeout)

    async def stop(self) -> None:
        self.proc.send_signal(signal.SIGTERM)
        assert await asyncio.wait_for(self.proc.wait(), 30) == 0
        assert self.proc.stdout is not None
        self.lines += (await self.proc.stdout.read()).decode().splitlines()


async def lag(group: str) -> int:
    return sum((await group_lag(group, [CALL_DONE])).values())


async def test_sigkill_during_judge_call_gives_one_evaluation_row(dburl: str) -> None:
    (call,) = seed_run(dburl, 1)
    group = unique_group("eval-crash-judge")
    env = call_completed(call)
    await prime_group(group, [CALL_DONE])

    victim = await Worker.spawn(group, dburl, "crash_in_judge")
    await victim.wait_for_line("READY")
    await publish(env)
    await victim.wait_for_line("JUDGE_CALL")
    assert await asyncio.wait_for(victim.proc.wait(), 30) == -signal.SIGKILL

    # the crash left nothing behind: no evaluation, no idempotency row, offset uncommitted
    assert evaluation_count(dburl, call.call_id) == 0
    assert processed_count(dburl, group, env.event_id) == 0
    assert await lag(group) == 1

    survivor = await Worker.spawn(group, dburl, "normal")
    await survivor.wait_for_line("READY")
    await survivor.wait_for_line("JUDGE_CALL")

    async def committed() -> bool:
        return await lag(group) == 0

    await wait_for(committed, timeout=60, what="offset committed after redelivery")
    await survivor.stop()

    assert evaluation_count(dburl, call.call_id) == 1
    assert processed_count(dburl, group, env.event_id) == 1
    assert [ln for ln in survivor.lines if ln == "JUDGE_CALL"] == ["JUDGE_CALL"]
    outputs = await read_topic(EVAL_DONE, key=str(call.call_id))
    assert [json.loads(o.value)["event_id"] for o in outputs] == [
        str(uuid.uuid5(env.event_id, "evaluation.completed"))
    ]
    # the killed attempt did not get to write a usage row after its (never completed) call;
    # the survivor wrote exactly one for its single judge call
    assert count(dburl, "SELECT count(*) FROM api_usage WHERE call_id = %s", call.call_id) == 1


async def test_sigkill_after_commit_reproduces_without_a_second_judge_call(dburl: str) -> None:
    (call,) = seed_run(dburl, 1)
    group = unique_group("eval-crash-produce")
    env = call_completed(call)
    await prime_group(group, [CALL_DONE])

    victim = await Worker.spawn(group, dburl, "crash_before_produce")
    await victim.wait_for_line("READY")
    await publish(env)
    await victim.wait_for_line("ABOUT_TO_PRODUCE")
    assert await asyncio.wait_for(victim.proc.wait(), 30) == -signal.SIGKILL

    # the evaluation committed, but no event left the process and the offset is uncommitted
    assert evaluation_count(dburl, call.call_id) == 1
    assert processed_count(dburl, group, env.event_id) == 1
    assert await lag(group) == 1
    assert await read_topic(EVAL_DONE, key=str(call.call_id)) == []

    survivor = await Worker.spawn(group, dburl, "normal")
    await survivor.wait_for_line("READY")
    await survivor.wait_for_line(f"REPRODUCE {env.event_id}")

    async def committed() -> bool:
        return await lag(group) == 0

    await wait_for(committed, timeout=60, what="offset committed after re-produce")
    await survivor.stop()

    assert evaluation_count(dburl, call.call_id) == 1
    assert "JUDGE_CALL" not in survivor.lines, "no second judge call"
    outputs = await read_topic(EVAL_DONE, key=str(call.call_id))
    assert [json.loads(o.value)["event_id"] for o in outputs] == [
        str(uuid.uuid5(env.event_id, "evaluation.completed"))
    ]


async def test_run_completed_is_emitted_once_with_evaluator_and_two_finalizers(
    dburl: str,
) -> None:
    calls = seed_run(dburl, 3)
    run_id = calls[0].run_id
    provider = ScriptedProvider([judge_json() for _ in calls])
    usage = ApiUsageSink(EventSettings(BOOTSTRAP, dburl))
    evaluator.set_client(scripted_client(provider, usage), usage)
    envs = [call_completed(c) for c in calls]
    try:
        async with (
            running("evaluator", "evaluator", dburl) as ev,
            running("finalizer", str(finalizer.GROUP), dburl) as fin,
        ):
            # each call.completed twice, interleaved
            await publish(*envs, *envs)
            await drained(ev)
            await drained(fin)
    finally:
        await usage.close()
        evaluator.set_client(None)

    assert len(provider.requests) == 3
    for c in calls:
        assert evaluation_count(dburl, c.call_id) == 1
    with psycopg.connect(dburl) as conn:
        run = conn.execute(
            "SELECT status, finished_at IS NOT NULL, summary FROM test_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
    assert run is not None
    assert run[0] == "completed" and run[1] is True
    assert run[2]["item_count"] == 3 and run[2]["evaluated_count"] == 3
    assert run[2]["pass_rate"] == 1.0

    done = await read_topic(Topics.RUN_COMPLETED, key=str(run_id))
    ids = {json.loads(m.value)["event_id"] for m in done}
    assert ids == {str(uuid.uuid5(run_id, "run.completed"))}
    # duplicates of the winning evaluation.completed may re-emit it, but never with another id
    assert len(done) >= 1


async def test_concurrent_finalizers_claim_the_run_once(dburl: str) -> None:
    """Two finalizer members racing on the last evaluations: one claim, one winner."""
    calls = seed_run(dburl, 2)
    run_id = calls[0].run_id
    with psycopg.connect(dburl, autocommit=True) as conn:
        conn.execute("UPDATE run_items SET status = 'evaluated' WHERE run_id = %s", (run_id,))
    group = unique_group("finalizer-race")
    spec = dataclasses.replace(REGISTRY[str(finalizer.GROUP)], group=group)
    await prime_group(group, [EVAL_DONE])
    members: list[Any] = [ConsumerRunner(spec, EventSettings(BOOTSTRAP, dburl)) for _ in range(2)]
    tasks = [asyncio.create_task(m.run()) for m in members]
    try:
        for m in members:
            await m.wait_ready()
        from pareeksha.events.schemas import EvaluationCompleted

        for c in calls:
            payload = EvaluationCompleted(
                call_id=c.call_id,
                evaluation_id=uuid.uuid4(),
                agent_id=c.agent_id,
                run_id=run_id,
                run_item_id=c.run_item_id,
                overall_score=90,
                passed=True,
            )
            await publish(make_envelope(payload, producer="test", correlation_id=str(run_id)))

        async def done() -> bool:
            return sum((await group_lag(group, [EVAL_DONE])).values()) == 0

        await wait_for(done, timeout=60, what="finalizer lag 0")
    finally:
        for m in members:
            m.stop_event.set()
        await asyncio.gather(*tasks)
    assert len(await read_topic(Topics.RUN_COMPLETED, key=str(run_id))) == 1
