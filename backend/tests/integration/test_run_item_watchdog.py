"""The reconciler's run-item passes against real Postgres (``runs.watchdog``).

A private migrated database per module: a sweep looks at every run, so rows other tests leave
behind in the shared database must not be in its way (nor it in theirs).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from pareeksha.db.session import make_engine
from pareeksha.events.settings import libpq_url
from pareeksha.events.topics import Topics
from pareeksha.runs.slots import release_slot
from pareeksha.runs.watchdog import StaleSweep, give_up_dead_lettered
from pareeksha.simulation import store
from pareeksha.workers.reconciler import Reconciler
from tests.conftest import Tenant, _migrated_database, new_tenant
from tests.integration.runs_support import settings_for
from tests.integration.test_run_slots import Run, _new_run

AsyncConn = psycopg.AsyncConnection[Any]
STALE_S = 3600.0


@pytest.fixture(scope="module")
def own_url() -> Iterator[str]:
    yield from _migrated_database()


@pytest.fixture
async def conn(own_url: str) -> AsyncIterator[AsyncConn]:
    async with await psycopg.AsyncConnection.connect(libpq_url(own_url), autocommit=True) as c:
        # each test starts with no live run: earlier tests' items must not be swept here
        await c.execute("UPDATE test_runs SET status = 'completed' WHERE status = 'running'")
        yield c


@pytest.fixture
async def tenant(own_url: str) -> Tenant:
    engine = make_engine(own_url, poolclass=NullPool)
    try:
        return await new_tenant(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


async def _scalar(conn: AsyncConn, sql: str, *params: Any) -> Any:
    cur = await conn.execute(sql, params)
    row = await cur.fetchone()
    assert row is not None
    return row[0]


async def _now(conn: AsyncConn) -> datetime:
    value: datetime = await _scalar(conn, "SELECT now()")
    return value


async def _running(conn: AsyncConn, tenant: Tenant, items: int, active: int) -> Run:
    """A running run whose first ``active`` items hold a slot (``in_progress``, no call yet)."""
    run = await _new_run(conn, tenant, items=items, cap=max(active, 1))
    await conn.execute(
        "UPDATE test_runs SET status = 'running', active_calls = %s WHERE id = %s", (active, run.id)
    )
    for item in run.items[:active]:
        await conn.execute("UPDATE run_items SET status = 'in_progress' WHERE id = %s", (item,))
    return run


async def _call(conn: AsyncConn, tenant: Tenant, run: Run, item: uuid.UUID, started: Any) -> None:
    await conn.execute(
        "INSERT INTO calls (id, project_id, source, status, agent_id, run_item_id, metadata, "
        "started_at) VALUES (%s, %s, 'simulation', 'in_progress', %s, %s, %s, %s)",
        (store.call_id_for(item), tenant.project_id, run.agent_id, item, Jsonb({}), started),
    )


async def _item(conn: AsyncConn, item: uuid.UUID) -> tuple[str, str | None]:
    cur = await conn.execute("SELECT status, last_error FROM run_items WHERE id = %s", (item,))
    row = await cur.fetchone()
    assert row is not None
    return row[0], row[1]


async def _active(conn: AsyncConn, run_id: uuid.UUID) -> int:
    return int(await _scalar(conn, "SELECT active_calls FROM test_runs WHERE id = %s", run_id))


async def _progress_events(conn: AsyncConn, item: uuid.UUID) -> list[str]:
    cur = await conn.execute(
        "SELECT envelope->'payload'->>'status' FROM outbox_events "
        "WHERE topic = %s AND envelope->'payload'->>'run_item_id' = %s",
        (Topics.PROGRESS.value, str(item)),
    )
    return [r[0] for r in await cur.fetchall()]


# ------------------------------------------------------------------------------- stale sweep


async def test_a_stale_item_is_given_up_once_and_a_fresh_one_is_left_alone(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _running(conn, tenant, items=3, active=2)
    stale, fresh = run.items[0], run.items[1]
    now = await _now(conn)
    await _call(conn, tenant, run, stale, now - timedelta(seconds=STALE_S + 1))
    await _call(conn, tenant, run, fresh, now - timedelta(seconds=STALE_S - 60))
    sweep = StaleSweep(stale_after_s=STALE_S)

    done = await sweep.run(conn)

    assert [g.run_item_id for g in done] == [stale]
    assert await _item(conn, stale) == ("error", "infra: stale: no progress for 60 minutes")
    assert (await _item(conn, fresh))[0] == "in_progress"
    cur = await conn.execute(
        "SELECT status, end_reason, error FROM calls WHERE run_item_id = %s", (stale,)
    )
    assert await cur.fetchone() == (
        "error",
        "infra_error",
        "infra: stale: no progress for 60 minutes",
    )
    assert await _active(conn, run.id) == 1  # exactly one slot back
    assert await _progress_events(conn, stale) == ["error"]

    assert await sweep.run(conn) == []  # a second sweep changes nothing
    assert await _active(conn, run.id) == 1
    assert await _progress_events(conn, stale) == ["error"]


async def test_an_item_exactly_at_the_threshold_is_not_stale(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _running(conn, tenant, items=1, active=1)
    now = await _now(conn)
    await _call(conn, tenant, run, run.items[0], now - timedelta(seconds=STALE_S))

    assert await StaleSweep(stale_after_s=STALE_S).run(conn, now=now) == []
    assert (await _item(conn, run.items[0]))[0] == "in_progress"

    later = now + timedelta(microseconds=1)
    done = await StaleSweep(stale_after_s=STALE_S).run(conn, now=later)
    assert [g.run_item_id for g in done] == [run.items[0]]


async def test_a_connecting_item_without_a_call_is_timed_from_when_the_sweep_first_saw_it(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _running(conn, tenant, items=2, active=2)
    for item in run.items:
        await conn.execute("UPDATE run_items SET status = 'connecting' WHERE id = %s", (item,))
    sweep = StaleSweep(stale_after_s=STALE_S)
    now = await _now(conn)

    assert await sweep.run(conn, now=now) == []
    assert set(sweep.first_seen) == set(run.items)
    later = now + timedelta(seconds=STALE_S + 1)
    # the second item's worker gets going: its call row appears shortly before the next sweep
    await _call(conn, tenant, run, run.items[1], later - timedelta(seconds=30))
    done = await sweep.run(conn, now=later)

    assert [g.run_item_id for g in done] == [run.items[0]]
    assert (await _item(conn, run.items[1]))[0] == "connecting"
    assert await _active(conn, run.id) == 1
    assert sweep.first_seen == {}  # the given-up item is forgotten, the other has a call now


async def test_a_fresh_sweep_process_never_gives_up_an_item_without_a_call_at_once(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _running(conn, tenant, items=1, active=1)
    await conn.execute("UPDATE run_items SET status = 'connecting' WHERE id = %s", (run.items[0],))
    assert await StaleSweep(stale_after_s=1).run(conn) == []
    assert (await _item(conn, run.items[0]))[0] == "connecting"


async def test_an_item_that_completes_while_the_sweep_waits_for_it_is_not_given_up(
    conn: AsyncConn, tenant: Tenant, own_url: str
) -> None:
    """The worker's save_call holds the run and item locks; the sweep's conditional transition
    waits, then finds the item completed: no error, and its slot is released once (by the
    worker), which two active items make visible (a double release would leave 0)."""
    run = await _running(conn, tenant, items=2, active=2)
    item = run.items[0]
    now = await _now(conn)
    await _call(conn, tenant, run, item, now - timedelta(seconds=STALE_S + 60))
    async with await psycopg.AsyncConnection.connect(libpq_url(own_url)) as worker:
        await worker.execute("SELECT 1 FROM test_runs WHERE id = %s FOR UPDATE", (run.id,))
        await worker.execute(
            "UPDATE run_items SET status = 'completed' WHERE id = %s "
            "AND status IN ('connecting', 'in_progress')",
            (item,),
        )
        await release_slot(worker, run.id)

        sweep = asyncio.create_task(StaleSweep(stale_after_s=STALE_S).run(conn))
        await asyncio.sleep(0.5)
        assert not sweep.done()  # blocked on the worker's locks
        await worker.commit()
        assert await asyncio.wait_for(sweep, 10) == []

    assert await _item(conn, item) == ("completed", None)
    assert await _active(conn, run.id) == 1
    assert await _progress_events(conn, item) == []


async def test_a_resumed_item_is_not_given_up_by_a_sweep_that_saw_its_old_state(
    conn: AsyncConn, tenant: Tenant
) -> None:
    """The conditional transition re-reads the call's start under the lock."""
    run = await _running(conn, tenant, items=1, active=1)
    item = run.items[0]
    now = await _now(conn)
    await _call(conn, tenant, run, item, now)  # (re)started since the caller looked
    cutoff = now - timedelta(seconds=STALE_S)
    assert await store.give_up_item(conn, item, "infra: stale", stale_before=cutoff) is None
    assert (await _item(conn, item))[0] == "in_progress"
    assert await _active(conn, run.id) == 1


async def test_stale_items_of_a_cancelled_run_are_given_up_and_finished_runs_ignored(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _running(conn, tenant, items=1, active=1)
    await conn.execute("UPDATE test_runs SET status = 'cancelled' WHERE id = %s", (run.id,))
    now = await _now(conn)
    await _call(conn, tenant, run, run.items[0], now - timedelta(days=1))
    done = await StaleSweep(stale_after_s=STALE_S).run(conn)
    assert [g.run_item_id for g in done] == [run.items[0]]
    assert await _active(conn, run.id) == 0


async def test_the_sweep_gives_up_at_most_its_batch_oldest_first(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _running(conn, tenant, items=3, active=3)
    now = await _now(conn)
    for age, item in zip((3, 1, 2), run.items, strict=True):
        await _call(conn, tenant, run, item, now - timedelta(days=age))
    sweep = StaleSweep(stale_after_s=STALE_S, limit=2)
    assert [g.run_item_id for g in await sweep.run(conn)] == [run.items[0], run.items[2]]
    assert [g.run_item_id for g in await sweep.run(conn)] == [run.items[1]]
    assert await _active(conn, run.id) == 0


# ------------------------------------------------------------------------ dead-letter pass


async def _dead_letter(
    conn: AsyncConn,
    topic: Topics,
    run_item_id: Any,
    *,
    group: str = "simulator",
    status: str = "open",
) -> None:
    await conn.execute(
        "INSERT INTO dead_letters (event_id, original_topic, key, consumer_group, envelope, "
        "error, attempts, status) VALUES (%s, %s, 'k', %s, %s, 'PermanentError: boom', 3, %s)",
        (
            uuid.uuid4(),
            topic.value,
            group,
            Jsonb({"payload": {"run_item_id": str(run_item_id)}}),
            status,
        ),
    )


async def test_items_whose_message_is_dead_lettered_are_given_up(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _running(conn, tenant, items=4, active=1)
    held, queued, replayed, evaluating = run.items
    await conn.execute("UPDATE run_items SET status = 'evaluating' WHERE id = %s", (evaluating,))
    await _dead_letter(conn, Topics.CALL_REQUESTED, held)
    await _dead_letter(conn, Topics.CALL_REQUESTED, queued)  # never parsed: never started
    await _dead_letter(conn, Topics.CALL_REQUESTED, replayed, status="replayed")
    await _dead_letter(conn, Topics.CALL_COMPLETED, evaluating, group="evaluator")
    await _dead_letter(conn, Topics.CALL_REQUESTED, "not-a-uuid")

    done = await give_up_dead_lettered(conn)

    assert {(g.run_item_id, g.status) for g in done} == {
        (held, "error"),
        (queued, "error"),
        (evaluating, "judge_error"),
    }
    assert await _item(conn, held) == ("error", "infra: dead-lettered: PermanentError: boom")
    assert (await _item(conn, queued))[0] == "error"
    assert await _item(conn, evaluating) == (
        "judge_error",
        "judge: dead-lettered: PermanentError: boom",
    )
    assert (await _item(conn, replayed))[0] == "queued"  # being retried by an operator
    assert await _active(conn, run.id) == 0  # only the slot-holding item gave one back
    cur = await conn.execute(
        "SELECT end_reason FROM calls WHERE run_item_id = ANY(%s) ORDER BY end_reason",
        ([held, queued],),
    )
    assert [r[0] for r in await cur.fetchall()] == ["infra_error", "infra_error"]

    assert await give_up_dead_lettered(conn) == []  # idempotent


async def test_the_reconciler_worker_runs_both_passes_and_the_slot_repair(
    conn: AsyncConn, tenant: Tenant, own_url: str
) -> None:
    run = await _running(conn, tenant, items=3, active=2)
    now = await _now(conn)
    await _call(conn, tenant, run, run.items[0], now - timedelta(days=1))
    await _dead_letter(conn, Topics.CALL_REQUESTED, run.items[1])
    worker = Reconciler(settings_for(own_url), stale_after_s=STALE_S)
    try:
        assert await worker.run_once() == 0
    finally:
        await worker._db.close()
    assert worker.given_up_total == 2
    assert await _active(conn, run.id) == 0
    assert (await _item(conn, run.items[2]))[0] == "queued"
