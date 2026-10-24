"""T-FR-SC-4: a promoted scenario links its source call (and survives listing and editing)."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import Tenant
from tests.integration.domain import API, build_world, make_call


async def test_promoted_scenario_keeps_its_source_call(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    world = await build_world(api, tenant)
    call = await make_call(session_factory, world, score=20)
    promoted = (
        await api.post(
            f"{API}/calls/{call.call_id}/promote",
            json={"failure_type": "policy_violation"},
            headers=tenant.admin,
        )
    ).json()
    sid = promoted["scenario_id"]

    fetched = (await api.get(f"{API}/scenarios/{sid}", headers=tenant.read)).json()
    assert (fetched["source"], fetched["source_call_id"]) == ("promoted", str(call.call_id))

    listed = (await api.get(f"{API}/scenarios", headers=tenant.read)).json()["items"]
    by_id = {s["id"]: s for s in listed}
    assert by_id[sid]["source_call_id"] == str(call.call_id)
    assert by_id[str(world.scenario_id)]["source"] == "manual"  # the original is untouched
    assert by_id[str(world.scenario_id)]["source_call_id"] is None

    edited = await api.patch(f"{API}/scenarios/{sid}", json={"max_turns": 9}, headers=tenant.admin)
    assert edited.status_code == 200
    assert edited.json()["source"] == "promoted" and edited.json()["source_call_id"] == str(
        call.call_id
    )
