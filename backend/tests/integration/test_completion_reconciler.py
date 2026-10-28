"""Run-completion reconciler, the ``evaluating`` transition and the cancelled-run rule.

Real Kafka and Postgres (the full schema in a throwaway database).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import pytest

from pareeksha.evaluation.completion_reconciler import reconcile_once, run_reconciler
from pareeksha.evaluation.pg_stores import PgFinalizerStore
from pareeksha.events.runtime import Database
from pareeksha.events.schemas import (
    EvaluationCompleted,
    RunCompletedSummary,
    make_envelope,
)
from pareeksha.events.settings import EventSettings
from pareeksha.events.topics import Topics
from pareeksha.llm.base import JSONCompletionRequest, JSONCompletionResult
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.workers import evaluator, finalizer
from tests.integration.eval_support import SeededCall, count, create_database, seed_run
from tests.integration.support import BOOTSTRAP, read_topic, wait_for
from tests.integration.test_evaluator_exactly_once import (
    call_completed,
    drained,
    publish,
    running,
    scripted_client,
)
from tests.unit.evaluation.fakes import ScriptedProvider, judge_json


@pytest.fixture
def dburl() -> Iterator[str]:
    with create_database() as url:
        yield url


@asynccontextmanager
async def aconn(url: str) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    conn = await psycopg.AsyncConnection.connect(url, autocommit=True)
    try:
        yield conn
    finally:
        await conn.close()


def set_items(url: str, run_id: uuid.UUID, status: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE run_items SET status = %s WHERE run_id = %s", (status, run_id))


def outbox_run_completed(url: str, run_id: uuid.UUID) -> int:
    return count(
        url,
        "SELECT count(*) FROM outbox_events WHERE topic = %s AND key = %s",
        Topics.RUN_COMPLETED.value,
        str(run_id),
    )


def eval_event(c: SeededCall) -> Any:
    payload = EvaluationCompleted(
        call_id=c.call_id,
        evaluation_id=uuid.uuid4(),
        agent_id=c.agent_id,
        run_id=c.run_id,
        run_item_id=c.run_item_id,
        overall_score=90,
        passed=True,
    )
    return make_envelope(payload, producer="test", correlation_id=str(c.run_id))


async def test_reconciler_completes_an_overdue_run_exactly_once(dburl: str) -> None:
    calls = seed_run(dburl, 2)
    run_id = calls[0].run_id
    set_items(dburl, run_id, "evaluated")  # the evaluation.completed events were lost
    async with aconn(dburl) as conn:
        assert await reconcile_once(conn) == [run_id]
        assert await reconcile_once(conn) == []  # idempotent
    with psycopg.connect(dburl) as c:
        run = c.execute(
            "SELECT status, finished_at IS NOT NULL, summary->>'item_count' "
            "FROM test_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        ids = {
            r[0]
            for r in c.execute(
                "SELECT id FROM outbox_events WHERE topic = %s",
                (Topics.RUN_COMPLETED.value,),
            ).fetchall()
        }
    assert run == ("completed", True, "2")
    assert ids == {uuid.uuid5(run_id, "run.completed")}
    assert outbox_run_completed(dburl, run_id) == 1


async def test_reconciler_leaves_unfinished_runs_alone(dburl: str) -> None:
    calls = seed_run(dburl, 2)
    set_items(dburl, calls[0].run_id, "evaluating")
    async with aconn(dburl) as conn:
        assert await reconcile_once(conn) == []
    assert count(dburl, "SELECT count(*) FROM outbox_events") == 0


async def test_racing_finalizer_and_reconcilers_complete_each_run_once(dburl: str) -> None:
    runs = [seed_run(dburl, 2) for _ in range(5)]
    for calls in runs:
        set_items(dburl, calls[0].run_id, "evaluated")
    async with running("finalizer", str(finalizer.GROUP), dburl) as fin:
        stop = asyncio.Event()

        async def hammer() -> None:
            async with aconn(dburl) as conn:
                while not stop.is_set():
                    await reconcile_once(conn)
                    await asyncio.sleep(0.01)

        tasks = [asyncio.create_task(hammer()) for _ in range(3)]
        await publish(*[eval_event(c) for calls in runs for c in calls])
        await drained(fin)
        await asyncio.sleep(1)
        stop.set()
        await asyncio.gather(*tasks)
    for calls in runs:
        run_id = calls[0].run_id
        via_topic = len(await read_topic(Topics.RUN_COMPLETED, key=str(run_id)))
        via_outbox = outbox_run_completed(dburl, run_id)
        # whichever side won the atomic claim produced it; the other side stayed silent
        assert via_topic + via_outbox == 1, (via_topic, via_outbox)
        assert (
            count(
                dburl,
                "SELECT count(*) FROM test_runs WHERE id = %s AND finished_at IS NOT NULL",
                run_id,
            )
            == 1
        )


async def test_a_cancelled_run_keeps_its_cancelled_status(dburl: str) -> None:
    calls = seed_run(dburl, 2)
    run_id = calls[0].run_id
    with psycopg.connect(dburl, autocommit=True) as c:
        c.execute("UPDATE test_runs SET status = 'cancelled' WHERE id = %s", (run_id,))
    set_items(dburl, run_id, "evaluated")  # even if every item finished anyway
    async with aconn(dburl) as conn:
        # the finalizer's own claim must not turn it into 'completed'
        summary = RunCompletedSummary(item_count=2, evaluated_count=2, error_count=0)
        assert await PgFinalizerStore(conn).claim_run_completion(run_id, "completed", summary)
        assert not await PgFinalizerStore(conn).claim_run_completion(run_id, "completed", summary)
    with psycopg.connect(dburl) as c:
        row = c.execute(
            "SELECT status, finished_at IS NOT NULL FROM test_runs WHERE id = %s", (run_id,)
        ).fetchone()
    assert row == ("cancelled", True)


async def test_reconciler_reports_a_cancelled_run_as_cancelled(dburl: str) -> None:
    calls = seed_run(dburl, 2)
    run_id = calls[0].run_id
    with psycopg.connect(dburl, autocommit=True) as c:
        c.execute("UPDATE test_runs SET status = 'cancelled' WHERE id = %s", (run_id,))
    set_items(dburl, run_id, "cancelled")
    async with aconn(dburl) as conn:
        assert await reconcile_once(conn) == [run_id]
    with psycopg.connect(dburl) as c:
        status = c.execute("SELECT status FROM test_runs WHERE id = %s", (run_id,)).fetchone()
        env = c.execute(
            "SELECT envelope FROM outbox_events WHERE topic = %s", (Topics.RUN_COMPLETED.value,)
        ).fetchone()
    assert status == ("cancelled",)
    assert env is not None and env[0]["payload"]["status"] == "cancelled"


async def test_reconciler_loop_runs_and_stops_cleanly(dburl: str) -> None:
    calls = seed_run(dburl, 1)
    run_id = calls[0].run_id
    set_items(dburl, run_id, "evaluated")
    stop = asyncio.Event()
    task = asyncio.create_task(run_reconciler(EventSettings(BOOTSTRAP, dburl), stop, interval=0.1))

    async def done() -> bool:
        return outbox_run_completed(dburl, run_id) == 1

    await wait_for(done, timeout=20, what="reconciler tick")
    stop.set()
    await asyncio.wait_for(task, 10)
    assert outbox_run_completed(dburl, run_id) == 1


class ObservingProvider(ScriptedProvider):
    """Records ``run_items.status`` as seen from another connection while the judge runs."""

    def __init__(self, url: str, item: uuid.UUID) -> None:
        super().__init__([judge_json()])
        self.url, self.item = url, item
        self.seen: list[str] = []

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        with psycopg.connect(self.url) as c:
            row = c.execute("SELECT status FROM run_items WHERE id = %s", (self.item,)).fetchone()
        assert row is not None
        self.seen.append(row[0])
        return await super().complete_json(request)


async def test_run_item_is_evaluating_while_the_judge_runs(dburl: str) -> None:
    (call,) = seed_run(dburl, 1)
    settings = EventSettings(BOOTSTRAP, dburl)
    provider = ObservingProvider(dburl, call.run_item_id)
    usage = ApiUsageSink(settings)
    status_db = Database(settings)
    evaluator.set_client(scripted_client(provider, usage), usage, status_db)
    try:
        async with running("evaluator", "evaluator", dburl) as ev:
            await publish(call_completed(call))
            await drained(ev)
    finally:
        await usage.close()
        await status_db.close()
        evaluator.set_client(None)
    assert provider.seen == ["evaluating"]
    with psycopg.connect(dburl) as c:
        assert c.execute(
            "SELECT status FROM run_items WHERE id = %s", (call.run_item_id,)
        ).fetchone() == ("evaluated",)
