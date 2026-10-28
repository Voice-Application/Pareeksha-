"""T-FR-AU-5: promote a failed call -> promoted scenario + regression test, linked to the call."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.db.models import Calls, Turns
from tests.conftest import Tenant
from tests.integration.domain import API, build_world, make_call

PROMOTE = {"failure_type": "wrong_fact", "baseline_score": 82, "notes": "Amount read-back"}


async def test_promote_creates_linked_scenario_and_blocking_test(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    call = await make_call(session_factory, world, score=41, critical=False)
    response = await api.post(
        f"{API}/calls/{call.call_id}/promote", json=PROMOTE, headers=tenant.admin
    )
    assert response.status_code == 201, response.text
    ids = response.json()

    scenario = (await api.get(f"{API}/scenarios/{ids['scenario_id']}", headers=tenant.read)).json()
    assert scenario["source"] == "promoted" and scenario["source_call_id"] == str(call.call_id)
    assert scenario["agent_id"] == str(world.agent_id)
    assert "Agent quoted the wrong EMI amount." in scenario["success_criteria"]  # judge summary
    assert "Amount read-back" in scenario["success_criteria"]  # reviewer notes
    assert {"regression", "wrong_fact"} <= set(scenario["tags"])
    assert scenario["caller_goal"].startswith("Convince the agent")  # the original scenario's goal

    tests = (
        await api.get(
            f"{API}/regression-tests", params={"agent_id": str(world.agent_id)}, headers=tenant.read
        )
    ).json()["items"]
    assert len(tests) == 1
    test = tests[0]
    assert test["id"] == ids["regression_test_id"] and test["scenario_id"] == ids["scenario_id"]
    assert test["source_call_id"] == str(call.call_id)
    assert (test["status"], test["baseline_score"], test["tolerance"]) == ("blocking", 82, 5)
    assert test["failure_type"] == "wrong_fact" and test["notes"] == "Amount read-back"
    assert test["persona_id"] == str(world.persona_id)  # same persona and line conditions
    assert test["noise_profile_id"] == str(world.noise_id)
    assert test["last_run_id"] is None and test["last_passed"] is None


async def test_promote_defaults_and_idempotency(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    call = await make_call(session_factory, world, score=30)
    url = f"{API}/calls/{call.call_id}/promote"
    first = await api.post(url, json={"failure_type": "loop"}, headers=tenant.admin)
    assert first.status_code == 201
    again = await api.post(url, json={"failure_type": "loop"}, headers=tenant.admin)
    assert again.json() == first.json()  # same pair, nothing duplicated
    other = await api.post(url, json={"failure_type": "wrong_fact"}, headers=tenant.admin)
    assert other.json()["regression_test_id"] != first.json()["regression_test_id"]
    listed = (
        await api.get(
            f"{API}/regression-tests", params={"agent_id": str(world.agent_id)}, headers=tenant.read
        )
    ).json()["items"]
    assert len(listed) == 2
    loop = next(t for t in listed if t["failure_type"] == "loop")
    assert (loop["status"], loop["baseline_score"]) == ("blocking", 80)  # defaults


async def test_promoting_an_uploaded_call_builds_the_scenario_from_what_the_caller_said(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    made = await make_call(session_factory, world, score=35)
    async with session_factory() as session:  # turn it into an upload with no run item
        call = await session.get(Calls, made.call_id)
        assert call is not None
        call.run_item_id, call.source, call.end_reason = None, "upload", "upload"
        await session.merge(
            Turns(
                call_id=call.id,
                idx=2,
                speaker="caller",
                text_="x",
                text_masked="my number is [PHONE]",
                start_ms=3000,
                end_ms=3900,
            )
        )
        await session.commit()
    response = await api.post(
        f"{API}/calls/{made.call_id}/promote", json=PROMOTE, headers=tenant.admin
    )
    assert response.status_code == 201, response.text
    scenario = (
        await api.get(f"{API}/scenarios/{response.json()['scenario_id']}", headers=tenant.read)
    ).json()
    assert scenario["source"] == "promoted" and scenario["source_call_id"] == str(made.call_id)
    assert "I paid. / my number is [PHONE]" in scenario["caller_goal"]  # masked text only
    test = (await api.get(f"{API}/regression-tests", headers=tenant.read)).json()["items"][0]
    assert test["persona_id"] is None and test["noise_profile_id"] is None


async def test_promote_validation_and_isolation(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    world = await build_world(api, tenant)
    call = await make_call(session_factory, world, score=30)
    url = f"{API}/calls/{call.call_id}/promote"
    assert (await api.post(url, json=PROMOTE, headers=other_tenant.admin)).status_code == 404
    assert (await api.post(url, json=PROMOTE, headers=tenant.read)).status_code == 403
    assert (
        await api.post(url, json={"failure_type": "nope"}, headers=tenant.admin)
    ).status_code == 400
    missing = f"{API}/calls/{uuid.uuid4()}/promote"
    assert (await api.post(missing, json=PROMOTE, headers=tenant.admin)).status_code == 404
    async with session_factory() as session:  # a call with no agent cannot become a test
        row = await session.get(Calls, call.call_id)
        assert row is not None
        row.agent_id = None
        await session.commit()
    no_agent = await api.post(url, json={"failure_type": "loop"}, headers=tenant.admin)
    assert no_agent.status_code == 400 and "no agent" in no_agent.json()["error"]["message"]
