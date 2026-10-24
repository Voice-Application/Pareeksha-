"""The planner: run.requested -> run_items -> call.requested (API-03, FR-RN-1, FR-RN-3).

``test_post_runs_to_call_requested_end_to_end`` is the whole path on real infrastructure: the API
writes the run and the outbox row, the outbox relay publishes to Kafka, the planner consumer
expands the matrix and produces ``call.requested`` keyed by ``run_item_id``. The other tests call
the handler on the migrated Postgres directly.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient

from pareeksha.events.consumer import REGISTRY, Ctx, PermanentError
from pareeksha.events.outbox import relay_once
from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import (
    CallRequested,
    Envelope,
    ProgressEvent,
    RunCompleted,
    RunRequested,
    make_envelope,
    parse_envelope,
)
from pareeksha.events.settings import libpq_url
from pareeksha.events.topics import Topics
from pareeksha.runs.matrix import expand_matrix
from pareeksha.workers import planner
from tests.conftest import Tenant
from tests.integration.harness import pipeline
from tests.integration.runs_support import API, make_fixture, plan_in_db, settings_for
from tests.integration.support import (
    BOOTSTRAP,
    group_lag,
    read_topic,
    unique_group,
    wait_for,
)

AsyncConn = psycopg.AsyncConnection[Any]


@pytest.fixture
async def conn(database_url: str) -> AsyncIterator[AsyncConn]:
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        yield c


async def _rows(conn: AsyncConn, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    cur = await conn.execute(sql, params)
    return await cur.fetchall()


def _spec() -> Any:
    """The real planner registration under a private group, so old topic data is not replayed."""
    return dataclasses.replace(REGISTRY[planner.GROUP], group=unique_group("planner"))


async def _call_requests(run_id: str) -> list[Any]:
    out = []
    for message in await read_topic(Topics.CALL_REQUESTED):
        env = Envelope[CallRequested].model_validate_json(message.value)
        if str(env.payload.run_id) == run_id:
            out.append((message, env))
    return out


# ---------------------------------------------------------------------------------- end to end


async def test_post_runs_to_call_requested_end_to_end(
    api: AsyncClient, tenant: Tenant, conn: AsyncConn, database_url: str
) -> None:
    fx = await make_fixture(api, tenant, scenarios=3, personas=2, profiles=2)
    created = await api.post(
        f"{API}/runs", json=fx.body(repeats=2, config={"seed": 99}), headers=tenant.admin
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    expected = 3 * 2 * 2 * 2
    assert created.json()["item_count"] == expected

    spec = _spec()
    async with pipeline(spec, settings=settings_for(database_url), with_retrier=False) as pl:
        # the outbox relay publishes the run's row to the real broker (rows other tests left
        # unpublished in this database are not ours to send)
        await conn.execute(
            "UPDATE outbox_events SET published_at = now() "
            "WHERE published_at IS NULL AND key <> %s",
            (run_id,),
        )
        producer = EventProducer(BOOTSTRAP, client_id="test-relay")
        await producer.start()
        try:
            result = await relay_once(conn, producer)
        finally:
            await producer.stop()
        assert result.published >= 1 and result.failed == 0
        published = await _rows(
            conn, "SELECT published_at IS NOT NULL FROM outbox_events WHERE key = %s", run_id
        )
        assert published == [(True,)]

        async def planned() -> bool:
            return len(await _call_requests(run_id)) == expected

        await wait_for(planned, timeout=40, what=f"{expected} call.requested events")
        group = pl.runner.group

    # run_items: one row per matrix cell, seeds as the matrix says
    items = await _rows(
        conn,
        "SELECT id, scenario_id, persona_id, noise_profile_id, seed, status "
        "FROM run_items WHERE run_id = %s",
        run_id,
    )
    cells = {
        (str(s), str(p), str(n), seed)
        for s, p, n, seed in (
            (c.scenario_id, c.persona_id, c.noise_profile_id, c.seed)
            for c in expand_matrix(
                run_seed=99,
                scenario_ids=[uuid.UUID(i) for i in fx.scenario_ids],
                persona_ids=[uuid.UUID(i) for i in fx.persona_ids],
                noise_profile_ids=[uuid.UUID(i) for i in fx.noise_profile_ids],
                repeats=2,
            )
        )
    }
    assert len(items) == expected and all(r[5] == "queued" for r in items)
    assert {(str(r[1]), str(r[2]), str(r[3]), r[4]) for r in items} == cells
    assert len({r[4] for r in items}) == expected  # every seed distinct

    # call.requested: one per item, keyed by run_item_id, ids derived from the run.requested id
    requests = await _call_requests(run_id)
    (outbox,) = await _rows(
        conn,
        "SELECT id FROM outbox_events WHERE key = %s AND topic = %s",
        run_id,
        Topics.RUN_REQUESTED.value,
    )
    request_event_id: uuid.UUID = outbox[0]
    by_item = {env.payload.run_item_id: (message, env) for message, env in requests}
    assert set(by_item) == {r[0] for r in items} and len(requests) == expected
    partitions = set()
    for item_id, (message, env) in by_item.items():
        assert message.key == str(item_id)
        assert env.event_id == uuid.uuid5(request_event_id, f"call.requested:{item_id}")
        assert env.causation_id == str(request_event_id) and env.correlation_id == run_id
        assert env.producer.startswith(group)
        assert str(env.payload.agent_id) == fx.agent_id and env.payload.regression_test_id is None
        partitions.add(message.partition)
    assert len(partitions) > 1  # keyed by run_item_id: one run spreads over the partitions

    progress = [
        parse_envelope(m.value).payload for m in await read_topic(Topics.PROGRESS, key=run_id)
    ]
    queued = [p for p in progress if isinstance(p, ProgressEvent) and p.status == "queued"]
    assert len(queued) == expected and all(p.scenario and p.persona for p in queued)

    # the planner group is caught up and the run now shows as planned
    assert set((await group_lag(group, [Topics.RUN_REQUESTED])).values()) == {0}
    run = (await api.get(f"{API}/runs/{run_id}", headers=tenant.read)).json()
    assert run["progress"]["total"] == expected and run["progress"]["queued"] == expected


async def test_redelivered_run_requested_adds_no_items_and_reproduces_the_events(
    api: AsyncClient, tenant: Tenant, conn: AsyncConn, database_url: str
) -> None:
    fx = await make_fixture(api, tenant, 2, 2, 1)
    run_id = (await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)).json()["id"]
    (row,) = await _rows(conn, "SELECT envelope FROM outbox_events WHERE key = %s", run_id)
    envelope = parse_envelope(row[0])
    spec = _spec()
    async with pipeline(
        spec, settings=settings_for(database_url), with_retrier=False, with_recorder=False
    ) as pl:
        await pl.send(envelope)
        await wait_for(
            _count_is(run_id, 4), timeout=40, what="4 call.requested after the first delivery"
        )
        first_ids = sorted(str(env.event_id) for _, env in await _call_requests(run_id))
        await pl.send(envelope)  # at-least-once: the very same event arrives again
        await prime_wait(pl.runner.group)
        second = await _call_requests(run_id)
    items = await _rows(conn, "SELECT count(*) FROM run_items WHERE run_id = %s", run_id)
    assert items == [(4,)]  # no duplicate items
    processed = await _rows(
        conn,
        "SELECT count(*) FROM processed_events WHERE consumer_group = %s",
        spec.group,
    )
    assert processed == [(1,)]
    # the duplicate re-produced the same events (same ids), so 8 messages carry 4 distinct ids
    assert sorted({str(env.event_id) for _, env in second}) == first_ids
    assert len(second) == 8


def _count_is(run_id: str, n: int) -> Any:
    async def probe() -> bool:
        return len(await _call_requests(run_id)) == n

    return probe


async def prime_wait(group: str) -> None:
    async def caught_up() -> bool:
        lag = await group_lag(group, [Topics.RUN_REQUESTED])
        return set(lag.values()) == {0}

    await wait_for(caught_up, timeout=30, what=f"{group} lag 0")  # offset is committed last


# ------------------------------------------------------------------- handler on Postgres


async def test_planning_twice_leaves_the_same_items(
    api: AsyncClient, tenant: Tenant, conn: AsyncConn, database_url: str
) -> None:
    fx = await make_fixture(api, tenant, 2, 2, 2)
    run_id = (await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)).json()["id"]
    first = await plan_in_db(database_url, run_id)
    ids = await _rows(conn, "SELECT id FROM run_items WHERE run_id = %s ORDER BY id", run_id)
    second = await plan_in_db(database_url, run_id)
    assert (
        await _rows(conn, "SELECT id FROM run_items WHERE run_id = %s ORDER BY id", run_id) == ids
    )
    assert len(ids) == 8
    assert len(first) == len(second) == 16  # call.requested + item.status per item
    payloads = [o.payload for o in first if isinstance(o.payload, CallRequested)]
    assert {p.run_item_id for p in payloads} == {i[0] for i in ids}
    assert all(
        o.discriminator == str(o.payload.run_item_id)
        for o in first
        if isinstance(o.payload, CallRequested)
    )


async def test_items_that_already_started_are_not_requested_again(
    api: AsyncClient, tenant: Tenant, conn: AsyncConn, database_url: str
) -> None:
    fx = await make_fixture(api, tenant, 2, 1, 1)
    run_id = (await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)).json()["id"]
    await plan_in_db(database_url, run_id)
    await conn.execute(
        "UPDATE run_items SET status = 'in_progress' WHERE id = "
        "(SELECT id FROM run_items WHERE run_id = %s LIMIT 1)",
        (run_id,),
    )
    again = await plan_in_db(database_url, run_id)
    assert len([o for o in again if isinstance(o.payload, CallRequested)]) == 1


async def test_a_cancelled_run_is_not_planned(
    api: AsyncClient, tenant: Tenant, conn: AsyncConn, database_url: str
) -> None:
    fx = await make_fixture(api, tenant, 2, 2, 1)
    run_id = (await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)).json()["id"]
    assert (await api.post(f"{API}/runs/{run_id}/cancel", headers=tenant.admin)).status_code == 202
    assert await plan_in_db(database_url, run_id) == []
    assert await _rows(conn, "SELECT count(*) FROM run_items WHERE run_id = %s", run_id) == [(0,)]


async def test_a_run_that_does_not_exist_is_a_permanent_error(
    conn: AsyncConn, tenant: Tenant, database_url: str
) -> None:
    payload = RunRequested(
        run_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        kind="matrix",
        scenario_ids=[uuid.uuid4()],
        persona_ids=[uuid.uuid4()],
        noise_profile_ids=[uuid.uuid4()],
    )
    envelope = make_envelope(payload, producer="test", correlation_id="x")
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        ctx = Ctx(tx=c, group="planner", topic="t", partition=0, offset=0, attempt=1)
        with pytest.raises(PermanentError, match="does not exist"):
            await planner.plan(envelope, ctx)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------- regression runs


async def _regression_setup(
    api: AsyncClient, tenant: Tenant, conn: AsyncConn, null_persona: bool = False
) -> tuple[Any, list[uuid.UUID]]:
    fx = await make_fixture(api, tenant, 2, 1, 1)
    ids = []
    for status, scenario in (("blocking", 0), ("blocking", 1), ("manual", 0), ("retired", 1)):
        cur = await conn.execute(
            "INSERT INTO regression_tests (project_id, agent_id, scenario_id, persona_id, "
            "noise_profile_id, failure_type, status) VALUES (%s, %s, %s, %s, %s, 'x', %s) "
            "RETURNING id",
            (
                tenant.project_id,
                fx.agent_id,
                fx.scenario_ids[scenario],
                None if null_persona else fx.persona_ids[0],
                fx.noise_profile_ids[0],
                status,
            ),
        )
        row = await cur.fetchone()
        assert row is not None
        ids.append(row[0])
    return fx, ids


async def _regression_run(conn: AsyncConn, tenant: Tenant, fx: Any) -> uuid.UUID:
    cur = await conn.execute(
        "INSERT INTO test_runs (project_id, agent_id, kind, config) "
        "VALUES (%s, %s, 'regression', '{\"max_concurrency\": 2}') RETURNING id",
        (tenant.project_id, fx.agent_id),
    )
    row = await cur.fetchone()
    assert row is not None
    run_id: uuid.UUID = row[0]
    return run_id


async def _plan_regression(
    database_url: str, run_id: uuid.UUID, fx: Any, statuses: list[str]
) -> Any:
    payload = RunRequested(
        run_id=run_id,
        agent_id=uuid.UUID(fx.agent_id),
        kind="regression",
        regression_statuses=statuses,  # type: ignore[arg-type]
        seed=5,
    )
    envelope = make_envelope(payload, producer="test", correlation_id=str(run_id))
    async with await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True) as c:
        async with c.transaction():
            ctx = Ctx(tx=c, group="planner", topic="t", partition=0, offset=0, attempt=1)
            return await planner.plan(envelope, ctx)  # type: ignore[arg-type]


async def test_regression_run_makes_one_item_per_selected_test(
    api: AsyncClient, tenant: Tenant, conn: AsyncConn, database_url: str
) -> None:
    fx, tests = await _regression_setup(api, tenant, conn)
    run_id = await _regression_run(conn, tenant, fx)
    outputs = await _plan_regression(database_url, run_id, fx, ["blocking"])
    items = await _rows(
        conn, "SELECT regression_test_id, status FROM run_items WHERE run_id = %s", run_id
    )
    assert {r[0] for r in items} == {tests[0], tests[1]}  # blocking only
    requests = [o.payload for o in outputs if isinstance(o.payload, CallRequested)]
    assert {p.regression_test_id for p in requests} == {tests[0], tests[1]}

    both = await _regression_run(conn, tenant, fx)
    await _plan_regression(database_url, both, fx, ["blocking", "manual"])
    seeds = await _rows(
        conn, "SELECT count(DISTINCT seed), count(*) FROM run_items WHERE run_id = %s", both
    )
    assert seeds == [(3, 3)]  # tests 0 and 2 share scenario/persona/profile yet get their own call


async def test_regression_test_without_persona_uses_the_projects_first_persona(
    api: AsyncClient, tenant: Tenant, conn: AsyncConn, database_url: str
) -> None:
    fx, _ = await _regression_setup(api, tenant, conn, null_persona=True)
    run_id = await _regression_run(conn, tenant, fx)
    await _plan_regression(database_url, run_id, fx, ["blocking"])
    personas = await _rows(
        conn, "SELECT DISTINCT persona_id FROM run_items WHERE run_id = %s", run_id
    )
    assert [str(r[0]) for r in personas] == [fx.persona_ids[0]]


async def test_empty_regression_suite_completes_the_run_at_once(
    api: AsyncClient, tenant: Tenant, conn: AsyncConn, database_url: str
) -> None:
    fx, _ = await _regression_setup(api, tenant, conn)
    run_id = await _regression_run(conn, tenant, fx)
    outputs = await _plan_regression(database_url, run_id, fx, ["scheduled"])  # none scheduled
    assert await _rows(
        conn, "SELECT status, finished_at IS NOT NULL FROM test_runs WHERE id = %s", run_id
    ) == [("completed", True)]
    completed = [o.payload for o in outputs if isinstance(o.payload, RunCompleted)]
    assert len(completed) == 1 and completed[0].summary.item_count == 0
    assert completed[0].summary.suite_passed is True and completed[0].kind == "regression"
    assert not [o for o in outputs if isinstance(o.payload, CallRequested)]
    assert json.dumps(completed[0].model_dump(mode="json"))  # serialisable
