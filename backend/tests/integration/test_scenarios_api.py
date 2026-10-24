"""Scenarios CRUD and bulk save against the real app and Postgres (FR-SC-1, FR-SC-3)."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.db import models
from tests.conftest import Tenant

SCENARIO: dict[str, Any] = {
    "title": "Already paid, wants confirmation",
    "caller_goal": "Convince the agent you paid via UPI 3 days ago.",
    "fixtures": {"customer_name": "Ravi Kumar", "emi_amount": 4000, "utr": "UTR-555-0100"},
    "reveal_rules": "Give the UTR only if asked.",
    "success_criteria": "Agent accepts the UTR and does not ask for payment again.",
    "must_say": ["confirm the amount"],
    "must_not_say": ["demand payment again"],
    "expected_tool_calls": [{"name": "record_utr", "args": {}, "order": 1}],
    "caller_speaks_first": True,
    "max_turns": 12,
    "tags": ["payment_dispute", "happy_path"],
}


async def _agent(api: AsyncClient, tenant: Tenant, name: str = "Bot") -> str:
    response = await api.post(
        "/api/v1/agents",
        json={"name": name, "endpoint_url": "ws://mock-agent:8765/ws"},
        headers=tenant.admin,
    )
    return str(response.json()["id"])


async def _scenario(api: AsyncClient, tenant: Tenant, **overrides: Any) -> dict[str, Any]:
    response = await api.post(
        "/api/v1/scenarios", json={**SCENARIO, **overrides}, headers=tenant.admin
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_create_get_and_all_fields_round_trip(api: AsyncClient, tenant: Tenant) -> None:
    agent_id = await _agent(api, tenant)
    created = await _scenario(api, tenant, agent_id=agent_id)
    assert created["source"] == "manual" and created["source_call_id"] is None
    fetched = (await api.get(f"/api/v1/scenarios/{created['id']}", headers=tenant.read)).json()
    assert fetched == created
    for field, value in {**SCENARIO, "agent_id": agent_id}.items():
        assert fetched[field] == value, field


async def test_agent_must_exist_in_the_project(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    foreign_agent = await _agent(api, other_tenant)
    for agent_id in (str(uuid.uuid4()), foreign_agent):
        response = await api.post(
            "/api/v1/scenarios", json={**SCENARIO, "agent_id": agent_id}, headers=tenant.admin
        )
        assert response.status_code == 400
        assert response.json()["error"]["details"]["agent_id"] == agent_id


async def test_patch_changes_only_given_fields_and_can_unlink_the_agent(
    api: AsyncClient, tenant: Tenant
) -> None:
    agent_id = await _agent(api, tenant)
    created = await _scenario(api, tenant, agent_id=agent_id)
    url = f"/api/v1/scenarios/{created['id']}"
    patched = (
        await api.patch(url, json={"title": "New title", "tags": []}, headers=tenant.admin)
    ).json()
    assert patched["title"] == "New title" and patched["tags"] == []
    assert patched["caller_goal"] == SCENARIO["caller_goal"] and patched["agent_id"] == agent_id
    assert patched["updated_at"] >= created["updated_at"]

    unlinked = (await api.patch(url, json={"agent_id": None}, headers=tenant.admin)).json()
    assert unlinked["agent_id"] is None  # reusable across agents
    ignored = (await api.patch(url, json={"title": None}, headers=tenant.admin)).json()
    assert ignored["title"] == "New title"  # null never blanks a required column

    relinked = await api.patch(url, json={"agent_id": agent_id}, headers=tenant.admin)
    assert relinked.json()["agent_id"] == agent_id
    bad = await api.patch(url, json={"agent_id": str(uuid.uuid4())}, headers=tenant.admin)
    assert bad.status_code == 400


async def test_list_filters_by_agent_and_tag(api: AsyncClient, tenant: Tenant) -> None:
    agent_a, agent_b = await _agent(api, tenant, "A"), await _agent(api, tenant, "B")
    one = await _scenario(api, tenant, title="one", agent_id=agent_a, tags=["x", "y"])
    two = await _scenario(api, tenant, title="two", agent_id=agent_b, tags=["y"])
    three = await _scenario(api, tenant, title="three", tags=[])

    async def ids(query: str) -> set[str]:
        page = (await api.get(f"/api/v1/scenarios{query}", headers=tenant.read)).json()
        return {s["id"] for s in page["items"]}

    assert await ids("") == {one["id"], two["id"], three["id"]}
    assert await ids(f"?agent_id={agent_a}") == {one["id"]}
    assert await ids("?tag=y") == {one["id"], two["id"]}
    assert await ids(f"?tag=y&agent_id={agent_b}") == {two["id"]}
    assert await ids("?tag=missing") == set()


async def test_bulk_save_is_atomic_and_marks_the_source(api: AsyncClient, tenant: Tenant) -> None:
    agent_id = await _agent(api, tenant)
    drafts = [{**SCENARIO, "title": f"draft {i}", "agent_id": agent_id} for i in range(3)]
    response = await api.post(
        "/api/v1/scenarios:bulk", json={"scenarios": drafts}, headers=tenant.admin
    )
    assert response.status_code == 201
    items = response.json()["items"]
    assert [s["title"] for s in items] == ["draft 0", "draft 1", "draft 2"]
    assert {s["source"] for s in items} == {"generated"}

    promoted = await api.post(
        "/api/v1/scenarios:bulk",
        json={"scenarios": [SCENARIO], "source": "promoted"},
        headers=tenant.admin,
    )
    assert promoted.json()["items"][0]["source"] == "promoted"

    before = (await api.get("/api/v1/scenarios", headers=tenant.read)).json()["items"]
    broken = await api.post(
        "/api/v1/scenarios:bulk",
        json={"scenarios": [SCENARIO, {**SCENARIO, "agent_id": str(uuid.uuid4())}]},
        headers=tenant.admin,
    )
    assert broken.status_code == 400
    after = (await api.get("/api/v1/scenarios", headers=tenant.read)).json()["items"]
    assert len(after) == len(before)  # nothing from the failed batch was saved
    empty = await api.post("/api/v1/scenarios:bulk", json={"scenarios": []}, headers=tenant.admin)
    assert empty.status_code == 400


async def test_delete_and_409_when_a_run_references_the_scenario(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    agent_id = await _agent(api, tenant)
    free = await _scenario(api, tenant, title="free")
    used = await _scenario(api, tenant, title="used")
    async with session_factory() as session:
        persona = models.Personas(
            project_id=tenant.project_id, name="p", language="kn-IN", voice_id="v"
        )
        noise = models.NoiseProfiles(project_id=tenant.project_id, name="n")
        run = models.TestRuns(project_id=tenant.project_id, agent_id=uuid.UUID(agent_id))
        session.add_all([persona, noise, run])
        await session.flush()
        session.add(
            models.RunItems(
                run_id=run.id,
                scenario_id=uuid.UUID(used["id"]),
                persona_id=persona.id,
                noise_profile_id=noise.id,
                seed=1,
            )
        )
        await session.commit()

    assert (
        await api.delete(f"/api/v1/scenarios/{free['id']}", headers=other_tenant.admin)
    ).status_code == 404
    deleted = await api.delete(f"/api/v1/scenarios/{free['id']}", headers=tenant.admin)
    assert deleted.status_code == 204 and deleted.content == b""
    assert (
        await api.get(f"/api/v1/scenarios/{free['id']}", headers=tenant.read)
    ).status_code == 404

    refused = await api.delete(f"/api/v1/scenarios/{used['id']}", headers=tenant.admin)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "conflict"
    assert (
        await api.get(f"/api/v1/scenarios/{used['id']}", headers=tenant.read)
    ).status_code == 200


async def test_not_found_and_validation(api: AsyncClient, tenant: Tenant) -> None:
    ghost = str(uuid.uuid4())
    assert (await api.get(f"/api/v1/scenarios/{ghost}", headers=tenant.read)).status_code == 404
    assert (
        await api.patch(f"/api/v1/scenarios/{ghost}", json={}, headers=tenant.admin)
    ).status_code == 404
    assert (await api.delete(f"/api/v1/scenarios/{ghost}", headers=tenant.admin)).status_code == 404
    bad = await api.post(
        "/api/v1/scenarios", json={**SCENARIO, "max_turns": 99}, headers=tenant.admin
    )
    assert bad.status_code == 400
    assert (
        await api.post("/api/v1/scenarios", json=SCENARIO, headers=tenant.read)
    ).status_code == 403
