"""PUT /calls/{id}/tool-calls: a bot (or its platform) reports its tool calls after the call."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.db import models
from pareeksha.evaluation.pg_stores import PgEvaluatorStore
from tests.conftest import Tenant
from tests.integration.audit_support import create_agent, fetch_rows, transaction, upload
from tests.integration.domain import API, build_world, make_call, outbox_for

TRACE = {"tool_calls": [{"name": "record_utr", "arguments": {"utr": "X1"}, "at_ms": 5}]}


async def _glass_box(api: AsyncClient, tenant: Tenant, agent_id: uuid.UUID, on: bool) -> None:
    response = await api.patch(
        f"{API}/agents/{agent_id}", json={"glass_box": on}, headers=tenant.admin
    )
    assert response.status_code == 200, response.text


async def test_second_put_replaces_the_first_and_marks_the_call(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    world = await build_world(api, tenant)
    await _glass_box(api, tenant, world.agent_id, False)
    call = await make_call(session_factory, world, score=None, call_status="in_progress")
    url = f"{API}/calls/{call.call_id}/tool-calls"
    first = await api.put(url, json=TRACE, headers=tenant.admin)
    assert first.status_code == 202 and first.json() == {"call_id": str(call.call_id)}
    second = await api.put(
        url,
        json={"tool_calls": [{"name": "a"}, {"name": "b", "result": {"ok": 1}}]},
        headers=tenant.admin,
    )
    assert second.status_code == 202
    rows = await fetch_rows(
        database_url, "SELECT * FROM tool_calls WHERE call_id = %s ORDER BY seq", call.call_id
    )
    assert [(r["seq"], r["name"], r["at_ms"], r["turn_idx"]) for r in rows] == [
        (0, "a", 0, None),
        (1, "b", 0, None),
    ]
    assert rows[1]["result"] == {"ok": 1}
    (row,) = await fetch_rows(
        database_url, "SELECT metadata FROM calls WHERE id = %s", call.call_id
    )
    assert row["metadata"]["tool_trace"] == "reported"
    # not completed: no re-evaluation yet
    assert await outbox_for(session_factory, "call_id", str(call.call_id)) == []

    assert (await api.put(url, json=TRACE, headers=other_tenant.admin)).status_code == 404
    assert (await api.put(url, json=TRACE, headers=tenant.read)).status_code == 403
    bad = await api.put(url, json={"tool_calls": [{"name": ""}]}, headers=tenant.admin)
    assert bad.status_code in (400, 422)


async def test_completed_call_is_re_evaluated(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    await _glass_box(api, tenant, world.agent_id, False)
    call = await make_call(session_factory, world, score=50)
    response = await api.put(
        f"{API}/calls/{call.call_id}/tool-calls", json=TRACE, headers=tenant.admin
    )
    assert response.status_code == 202
    assert len(await outbox_for(session_factory, "call_id", str(call.call_id))) == 1


async def test_glass_box_simulation_keeps_its_live_trace(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    await _glass_box(api, tenant, world.agent_id, True)
    call = await make_call(session_factory, world, score=50)
    response = await api.put(
        f"{API}/calls/{call.call_id}/tool-calls", json=TRACE, headers=tenant.admin
    )
    assert response.status_code == 409
    assert await outbox_for(session_factory, "call_id", str(call.call_id)) == []


async def test_evaluator_loads_a_reported_trace_for_an_upload(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    agent_id = await create_agent(api, tenant)
    call_id = (await upload(api, tenant, agent_id)).json()["call_id"]
    async with transaction(database_url) as ctx:
        snapshot = await PgEvaluatorStore(ctx.tx).load_snapshot(uuid.UUID(call_id))
    assert snapshot is not None and snapshot.tool_calls is None  # no trace: unknown

    response = await api.put(f"{API}/calls/{call_id}/tool-calls", json=TRACE, headers=tenant.admin)
    assert response.status_code == 202, response.text
    async with transaction(database_url) as ctx:
        snapshot = await PgEvaluatorStore(ctx.tx).load_snapshot(uuid.UUID(call_id))
    assert snapshot is not None and snapshot.tool_calls is not None
    assert [(t.name, t.args) for t in snapshot.tool_calls] == [("record_utr", {"utr": "X1"})]


async def _set_call(
    factory: async_sessionmaker[AsyncSession], call_id: uuid.UUID, **values: object
) -> None:
    async with factory() as session:
        row = await session.get(models.Calls, call_id)
        assert row is not None
        for key, value in values.items():
            setattr(row, key, value)
        await session.commit()


async def test_glass_box_decision_uses_the_calls_own_flag(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    await _glass_box(api, tenant, world.agent_id, False)  # agent flag turned off later...
    call = await make_call(session_factory, world, score=50)
    await _set_call(
        session_factory, call.call_id, metadata_={"glass_box": True}
    )  # ...call was live
    url = f"{API}/calls/{call.call_id}/tool-calls"
    assert (await api.put(url, json=TRACE, headers=tenant.admin)).status_code == 409


async def test_completed_simulation_without_a_run_item_cannot_be_reevaluated(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    await _glass_box(api, tenant, world.agent_id, False)
    call = await make_call(session_factory, world, score=50)
    await _set_call(session_factory, call.call_id, run_item_id=None)
    url = f"{API}/calls/{call.call_id}/tool-calls"
    assert (await api.put(url, json=TRACE, headers=tenant.admin)).status_code == 409


async def test_simulator_metadata_survives_a_report(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    world = await build_world(api, tenant)
    await _glass_box(api, tenant, world.agent_id, False)
    call = await make_call(session_factory, world, score=None, call_status="in_progress")
    await _set_call(session_factory, call.call_id, metadata_={"barge_in_attempts": [1]})
    url = f"{API}/calls/{call.call_id}/tool-calls"
    assert (await api.put(url, json=TRACE, headers=tenant.admin)).status_code == 202
    (row,) = await fetch_rows(
        database_url, "SELECT metadata FROM calls WHERE id = %s", call.call_id
    )
    assert row["metadata"] == {"barge_in_attempts": [1], "tool_trace": "reported"}
