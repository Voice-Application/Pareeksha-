"""POST /designer/commit against the real app and real Postgres: one transaction, tenant scope."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.conftest import Tenant

PERSONA = {"name": "Manju", "language": "kn-IN", "voice_id": "Prakash"}
NOISE = {"name": "clean_16k", "sample_rate": 16000}


def _draft(personas: list[dict[str, Any]], noise_ids: list[str], **agent: Any) -> dict[str, Any]:
    return {
        "agent": {
            "name": f"Designer bot {uuid.uuid4().hex[:6]}",
            "languages": ["kn-IN"],
            "endpoint_url": "ws://mock-agent:8765/ws",
            "expected_tools": [{"name": "lookup_loan"}],
            **agent,
        },
        "scenarios": [
            {
                "title": f"Scenario {i}",
                "caller_goal": "Pay the EMI",
                "success_criteria": "Agent confirms the amount",
                "expected_tool_calls": [{"name": "lookup_loan", "args": {}, "order": 1}],
            }
            for i in range(2)
        ],
        "personas": personas,
        "noise_profile_ids": noise_ids,
    }


async def _library(api: AsyncClient, tenant: Tenant) -> tuple[str, str]:
    persona = await api.post("/api/v1/personas", json=PERSONA, headers=tenant.admin)
    noise = await api.post("/api/v1/noise-profiles", json=NOISE, headers=tenant.admin)
    assert persona.status_code == 201 and noise.status_code == 201
    return persona.json()["id"], noise.json()["id"]


async def _count(factory: async_sessionmaker[AsyncSession], table: str, project: Any) -> int:
    async with factory() as session:
        row = await session.execute(
            text(f"SELECT count(*) FROM {table} WHERE project_id = :p"), {"p": project}
        )
        return int(row.scalar_one())


async def test_commit_creates_everything_bound_to_the_new_agent(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    persona_id, noise_id = await _library(api, tenant)
    new = {"name": "Tamil shopkeeper", "language": "ta-IN", "voice_id": "Kavya"}
    draft = _draft([{"existing_id": persona_id}, {"new": new}], [noise_id])
    resp = await api.post("/api/v1/designer/commit", json={"draft": draft}, headers=tenant.admin)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["scenario_ids"]) == 2 and len(body["persona_ids"]) == 2
    assert body["persona_ids"][0] == persona_id and body["noise_profile_ids"] == [noise_id]
    assert body["calls"] == 2 * 2 * 1
    s, p, line = (",".join(body[k]) for k in ("scenario_ids", "persona_ids", "noise_profile_ids"))
    assert body["run_wizard_path"] == (
        f"/runs/new?agent={body['agent_id']}&s={s}&p={p}&l={line}&step=review"
    )
    agent = (await api.get(f"/api/v1/agents/{body['agent_id']}", headers=tenant.read)).json()
    assert agent["endpoint_url"] == "ws://mock-agent:8765/ws"
    scenarios = (
        await api.get(
            "/api/v1/scenarios", params={"agent_id": body["agent_id"]}, headers=tenant.read
        )
    ).json()["items"]
    assert {sc["id"] for sc in scenarios} == set(body["scenario_ids"])
    assert await _count(session_factory, "personas", tenant.project_id) == 2  # 1 existing + 1 new


async def test_a_failure_rolls_everything_back(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    _, noise_id = await _library(api, tenant)
    # the second new persona clashes with the first one's name: the unique violation is a 409 and
    # the agent and scenarios created before it must not survive
    clash = {"name": "Twin", "language": "hi-IN", "voice_id": "v"}
    draft = _draft([{"new": clash}, {"new": clash}], [noise_id])
    resp = await api.post("/api/v1/designer/commit", json={"draft": draft}, headers=tenant.admin)
    assert resp.status_code == 409
    assert await _count(session_factory, "agents", tenant.project_id) == 0
    assert await _count(session_factory, "scenarios", tenant.project_id) == 0
    assert await _count(session_factory, "personas", tenant.project_id) == 1  # only the library one


async def test_agent_name_clash_is_409(api: AsyncClient, tenant: Tenant) -> None:
    persona_id, noise_id = await _library(api, tenant)
    draft = _draft([{"existing_id": persona_id}], [noise_id], name="Same name")
    first = await api.post("/api/v1/designer/commit", json={"draft": draft}, headers=tenant.admin)
    assert first.status_code == 201
    second = await api.post("/api/v1/designer/commit", json={"draft": draft}, headers=tenant.admin)
    assert second.status_code == 409


async def test_missing_endpoint_is_422(api: AsyncClient, tenant: Tenant) -> None:
    persona_id, noise_id = await _library(api, tenant)
    draft = _draft([{"existing_id": persona_id}], [noise_id], endpoint_url=None)
    resp = await api.post("/api/v1/designer/commit", json={"draft": draft}, headers=tenant.admin)
    assert resp.status_code == 422
    assert "draft.agent.endpoint_url" in resp.json()["error"]["message"]


async def test_ids_of_another_project_are_404(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    persona_id, noise_id = await _library(api, tenant)
    foreign_persona, foreign_noise = await _library(api, other_tenant)
    bad_persona = _draft([{"existing_id": foreign_persona}], [noise_id])
    resp = await api.post(
        "/api/v1/designer/commit", json={"draft": bad_persona}, headers=tenant.admin
    )
    assert resp.status_code == 404
    bad_noise = _draft([{"existing_id": persona_id}], [foreign_noise])
    resp = await api.post(
        "/api/v1/designer/commit", json={"draft": bad_noise}, headers=tenant.admin
    )
    assert resp.status_code == 404
    assert await _count(session_factory, "agents", tenant.project_id) == 0


async def test_read_key_cannot_commit_or_chat(api: AsyncClient, tenant: Tenant) -> None:
    persona_id, noise_id = await _library(api, tenant)
    draft = _draft([{"existing_id": persona_id}], [noise_id])
    resp = await api.post("/api/v1/designer/commit", json={"draft": draft}, headers=tenant.read)
    assert resp.status_code == 403
    chat = {"messages": [{"role": "user", "content": "hi"}]}
    assert (
        await api.post("/api/v1/designer/chat", json=chat, headers=tenant.read)
    ).status_code == 403
