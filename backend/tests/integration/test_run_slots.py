"""Per-run slots never exceed the cap; the reconciler repairs a leaked slot (API-03, NFR-4b).

Real Postgres, concurrent connections. The last test also drives the real consumer framework on
Kafka with a simulator-shaped handler built on ``start_item``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest

from pareeksha.events.consumer import ConsumerSpec, Ctx, Outgoing, Throttled
from pareeksha.events.schemas import CallRequested, Envelope, make_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.events.topics import Topics
from pareeksha.runs.slots import (
    StartResult,
    reconcile_slots,
    release_slot,
    start_item,
    take_slot,
)
from pareeksha.workers.reconciler import Reconciler
from tests.conftest import Tenant
from tests.integration.harness import pipeline
from tests.integration.runs_support import settings_for
from tests.integration.support import read_topic, wait_for

AsyncConn = psycopg.AsyncConnection[Any]


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConn]:
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        yield c


@dataclass
class Run:
    id: uuid.UUID
    agent_id: uuid.UUID
    scenario_id: uuid.UUID
    persona_id: uuid.UUID
    noise_profile_id: uuid.UUID
    items: list[uuid.UUID]


async def _insert(conn: AsyncConn, sql: str, *params: Any) -> uuid.UUID:
    cur = await conn.execute(sql, params)
    row = await cur.fetchone()
    assert row is not None
    value: uuid.UUID = row[0]
    return value


async def _new_run(conn: AsyncConn, tenant: Tenant, items: int, cap: int | None = 3) -> Run:
    """A run with ``items`` queued run_items (rows made with SQL: the planner is not under test)."""
    suffix = uuid.uuid4().hex[:8]
    project = tenant.project_id
    agent = await _insert(
        conn,
        "INSERT INTO agents (project_id, name, endpoint_url) VALUES (%s, %s, 'ws://x') "
        "RETURNING id",
        project,
        f"a-{suffix}",
    )
    scenario = await _insert(
        conn,
        "INSERT INTO scenarios (project_id, title, caller_goal, success_criteria) "
        "VALUES (%s, %s, 'g', 's') RETURNING id",
        project,
        f"s-{suffix}",
    )
    persona = await _insert(
        conn,
        "INSERT INTO personas (project_id, name, language, tts_model, voice_id) "
        "VALUES (%s, %s, 'kn-IN', 'timbre-v3.0', 'Prakash') RETURNING id",
        project,
        f"p-{suffix}",
    )
    profile = await _insert(
        conn,
        "INSERT INTO noise_profiles (project_id, name, sample_rate) VALUES (%s, %s, 8000) "
        "RETURNING id",
        project,
        f"n-{suffix}",
    )
    config = "{}" if cap is None else f'{{"max_concurrency": {cap}}}'
    run = await _insert(
        conn,
        "INSERT INTO test_runs (project_id, agent_id, config) VALUES (%s, %s, %s::jsonb) "
        "RETURNING id",
        project,
        agent,
        config,
    )
    item_ids = [
        await _insert(
            conn,
            "INSERT INTO run_items (run_id, scenario_id, persona_id, noise_profile_id, seed) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            run,
            scenario,
            persona,
            profile,
            seed,
        )
        for seed in range(items)
    ]
    return Run(run, agent, scenario, persona, profile, item_ids)


async def _scalar(conn: AsyncConn, sql: str, *params: Any) -> Any:
    cur = await conn.execute(sql, params)
    row = await cur.fetchone()
    assert row is not None
    return row[0]


async def _active(conn: AsyncConn, run_id: uuid.UUID) -> int:
    return int(await _scalar(conn, "SELECT active_calls FROM test_runs WHERE id = %s", run_id))


async def _held(conn: AsyncConn, run_id: uuid.UUID) -> int:
    return int(
        await _scalar(
            conn,
            "SELECT count(*) FROM run_items WHERE run_id = %s "
            "AND status IN ('connecting', 'in_progress')",
            run_id,
        )
    )


async def _start(url: str, run_id: uuid.UUID, item_id: uuid.UUID) -> StartResult:
    """One simulator: its own connection, like a separate worker process."""
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as c:
        return await start_item(c, run_id, item_id)


# ---------------------------------------------------------------------------------- the cap


async def test_concurrent_simulators_never_exceed_max_concurrency(
    conn: AsyncConn, tenant: Tenant, database_url: str
) -> None:
    url = libpq_url(database_url)
    run = await _new_run(conn, tenant, items=12, cap=3)
    results = await asyncio.gather(*[_start(url, run.id, i) for i in run.items])
    assert Counter(results) == {StartResult.TAKEN: 3, StartResult.THROTTLED: 9}
    assert await _active(conn, run.id) == 3 == await _held(conn, run.id)
    state = await _scalar(
        conn, "SELECT status || started_at::text FROM test_runs WHERE id = %s", run.id
    )
    assert state.startswith("running")  # the first start moved the run queued -> running


async def test_a_released_slot_goes_to_the_next_waiting_item(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _new_run(conn, tenant, items=3, cap=2)
    assert [await start_item(conn, run.id, i) for i in run.items] == [
        StartResult.TAKEN,
        StartResult.TAKEN,
        StartResult.THROTTLED,
    ]
    await conn.execute("UPDATE run_items SET status = 'completed' WHERE id = %s", (run.items[0],))
    await release_slot(conn, run.id)  # what the simulator does when it saves the call
    assert await start_item(conn, run.id, run.items[2]) is StartResult.TAKEN
    assert await _active(conn, run.id) == 2 == await _held(conn, run.id)


async def test_cap_comes_from_each_runs_config_and_defaults_to_three(
    conn: AsyncConn, tenant: Tenant
) -> None:
    one = await _new_run(conn, tenant, items=3, cap=1)
    default = await _new_run(conn, tenant, items=5, cap=None)
    assert [await take_slot(conn, one.id) for _ in one.items] == [True, False, False]
    assert [await take_slot(conn, default.id) for _ in default.items] == [True] * 3 + [False] * 2


async def test_redelivery_resumes_the_item_without_a_second_slot(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _new_run(conn, tenant, items=1, cap=1)
    assert await start_item(conn, run.id, run.items[0]) is StartResult.TAKEN
    # the simulator crashed mid-call and Kafka redelivers the message: the item still holds it
    assert await start_item(conn, run.id, run.items[0]) is StartResult.RESUMED
    assert await _active(conn, run.id) == 1


async def test_cancelled_finished_and_unknown_items_are_skipped(
    conn: AsyncConn, tenant: Tenant
) -> None:
    run = await _new_run(conn, tenant, items=3, cap=3)
    cancelled, evaluated, waiting = run.items
    await conn.execute("UPDATE run_items SET status = 'cancelled' WHERE id = %s", (cancelled,))
    await conn.execute("UPDATE run_items SET status = 'evaluated' WHERE id = %s", (evaluated,))
    assert await start_item(conn, run.id, cancelled) is StartResult.SKIPPED
    assert await start_item(conn, run.id, evaluated) is StartResult.SKIPPED
    assert await start_item(conn, run.id, uuid.uuid4()) is StartResult.SKIPPED
    other = await _new_run(conn, tenant, items=0)
    assert await start_item(conn, other.id, waiting) is StartResult.SKIPPED  # another run's item
    assert await start_item(conn, uuid.uuid4(), waiting) is StartResult.SKIPPED  # no such run
    await conn.execute("UPDATE test_runs SET status = 'cancelled' WHERE id = %s", (run.id,))
    assert await start_item(conn, run.id, waiting) is StartResult.SKIPPED
    assert await _active(conn, run.id) == 0


async def test_release_never_goes_below_zero(conn: AsyncConn, tenant: Tenant) -> None:
    run = await _new_run(conn, tenant, items=0)
    await release_slot(conn, run.id)
    await release_slot(conn, run.id)
    assert await _active(conn, run.id) == 0


# ---------------------------------------------------------------------------------- reconciler


async def test_reconciler_repairs_a_leaked_slot_and_a_missing_one(
    conn: AsyncConn, tenant: Tenant
) -> None:
    leaked = await _new_run(conn, tenant, items=2, cap=2)
    for item in leaked.items:
        assert await start_item(conn, leaked.id, item) is StartResult.TAKEN
    # both calls finished but their slots were never released (a crash between save and release)
    await conn.execute("UPDATE run_items SET status = 'evaluated' WHERE run_id = %s", (leaked.id,))
    assert await _active(conn, leaked.id) == 2 and await _held(conn, leaked.id) == 0

    missing = await _new_run(conn, tenant, items=2, cap=2)
    # two calls are active but the counter says 0
    await conn.execute(
        "UPDATE run_items SET status = 'in_progress' WHERE run_id = %s", (missing.id,)
    )
    healthy = await _new_run(conn, tenant, items=1, cap=2)
    assert await start_item(conn, healthy.id, healthy.items[0]) is StartResult.TAKEN

    mine = {leaked.id, missing.id, healthy.id}
    repairs = {r.run_id: r for r in await reconcile_slots(conn) if r.run_id in mine}
    assert (repairs[leaked.id].was, repairs[leaked.id].now) == (2, 0)
    assert (repairs[missing.id].was, repairs[missing.id].now) == (0, 2)
    assert healthy.id not in repairs
    assert await _active(conn, leaked.id) == 0 and await _active(conn, missing.id) == 2
    assert await _active(conn, healthy.id) == 1
    assert [r for r in await reconcile_slots(conn) if r.run_id in mine] == []  # idempotent

    # a run that the leak held at its cap can start work again once repaired
    stuck = await _new_run(conn, tenant, items=3, cap=2)
    await conn.execute("UPDATE test_runs SET active_calls = 2 WHERE id = %s", (stuck.id,))
    assert await start_item(conn, stuck.id, stuck.items[0]) is StartResult.THROTTLED
    await reconcile_slots(conn)
    assert await start_item(conn, stuck.id, stuck.items[0]) is StartResult.TAKEN


async def test_reconciler_is_safe_while_simulators_run(
    conn: AsyncConn, tenant: Tenant, database_url: str
) -> None:
    """Many start/release cycles interleaved with reconciliation: the cap holds throughout."""
    url = libpq_url(database_url)
    cap = 3
    run = await _new_run(conn, tenant, items=30, cap=cap)
    peak = 0
    stop = asyncio.Event()

    async def simulator(item: uuid.UUID) -> None:
        async with await psycopg.AsyncConnection.connect(url, autocommit=True) as c:
            while True:
                result = await start_item(c, run.id, item)
                if result is StartResult.THROTTLED:
                    await asyncio.sleep(0.01)
                    continue
                assert result is StartResult.TAKEN
                await asyncio.sleep(0.01)  # the "call"
                async with c.transaction():  # saving the call releases the slot atomically
                    await c.execute(
                        "UPDATE run_items SET status = 'completed' WHERE id = %s", (item,)
                    )
                    await release_slot(c, run.id)
                return

    async def reconciler() -> None:
        async with await psycopg.AsyncConnection.connect(url, autocommit=True) as c:
            while not stop.is_set():
                await reconcile_slots(c)
                await asyncio.sleep(0)

    async def sampler() -> None:
        nonlocal peak
        async with await psycopg.AsyncConnection.connect(url, autocommit=True) as c:
            while not stop.is_set():
                peak = max(peak, await _active(c, run.id), await _held(c, run.id))
                await asyncio.sleep(0)

    background = [asyncio.create_task(reconciler()), asyncio.create_task(sampler())]
    await asyncio.wait_for(asyncio.gather(*[simulator(i) for i in run.items]), 60)
    stop.set()
    await asyncio.gather(*background)
    assert 1 <= peak <= cap
    assert await _active(conn, run.id) == 0 == await _held(conn, run.id)
    done = await _scalar(
        conn, "SELECT count(*) FROM run_items WHERE run_id = %s AND status = 'completed'", run.id
    )
    assert done == 30


async def test_reconciler_worker_repairs_on_its_interval_and_stops_cleanly(
    conn: AsyncConn, tenant: Tenant, database_url: str
) -> None:
    run = await _new_run(conn, tenant, items=1, cap=2)
    await conn.execute("UPDATE test_runs SET active_calls = 2 WHERE id = %s", (run.id,))
    worker = Reconciler(settings_for(database_url), interval=0.2)
    task = asyncio.create_task(worker.run())
    try:

        async def repaired() -> bool:
            return await _active(conn, run.id) == 0

        await wait_for(repaired, timeout=10, what="leaked slot repaired by the worker")
    finally:
        worker.stop_event.set()
        await asyncio.wait_for(task, 10)
    assert worker.repaired_total >= 1


async def test_reconciler_worker_survives_an_unreachable_database() -> None:
    worker = Reconciler(
        settings_for("postgresql://pareeksha:pareeksha@127.0.0.1:1/none"), interval=0.1
    )
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.5)
    assert not task.done()  # keeps looping instead of crashing
    worker.stop_event.set()
    await asyncio.wait_for(task, 10)
    with pytest.raises(psycopg.OperationalError):
        await worker.run_once()


# ---------------------------------------------------------------------------------- Kafka


async def test_throttled_calls_wait_in_retry_30s_without_using_an_attempt(
    conn: AsyncConn, tenant: Tenant, database_url: str
) -> None:
    """A simulator-shaped consumer on real Kafka: cap 2 of 5 calls, the other 3 are throttled."""
    run = await _new_run(conn, tenant, items=5, cap=2)
    started: list[uuid.UUID] = []

    async def simulate(env: Envelope[CallRequested], ctx: Ctx) -> list[Outgoing]:
        result = await start_item(ctx.tx, env.payload.run_id, env.payload.run_item_id)
        if result is StartResult.THROTTLED:
            raise Throttled("run is at max_concurrency")
        started.append(env.payload.run_item_id)
        return []

    spec = ConsumerSpec(
        group=f"sim-{uuid.uuid4().hex[:8]}", topics=(Topics.CALL_REQUESTED,), handler=simulate
    )

    async def throttled_copies() -> list[Any]:
        return [
            m
            for m in await read_topic(Topics.RETRY_30S)
            if m.headers.get("x-consumer-group") == spec.group
        ]

    async with pipeline(spec, settings=settings_for(database_url), with_recorder=False) as pl:
        for item in run.items:
            payload = CallRequested(
                run_id=run.id,
                run_item_id=item,
                agent_id=run.agent_id,
                scenario_id=run.scenario_id,
                persona_id=run.persona_id,
                noise_profile_id=run.noise_profile_id,
                seed=1,
            )
            await pl.send(make_envelope(payload, producer="test", correlation_id=str(run.id)))

        async def three_waiting() -> bool:
            return len(await throttled_copies()) == 3

        await wait_for(three_waiting, timeout=30, what="3 throttled copies on retry.30s")
    retries = await throttled_copies()
    envelopes = [Envelope[CallRequested].model_validate_json(m.value) for m in retries]
    assert all(m.headers["x-reason"] == "throttled" for m in retries)
    assert all(e.attempt == 1 for e in envelopes)  # waiting for a slot costs no attempt
    assert len(started) == 2 and await _active(conn, run.id) == 2
    assert {e.payload.run_item_id for e in envelopes}.isdisjoint(started)
