"""Agents CRUD against the real app and real Postgres (FR-AG-1, FR-AG-2)."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

from tests.conftest import Tenant

AGENT: dict[str, Any] = {
    "name": "EMI Reminder Bot",
    "description": "Outbound bot for Shakti Finance (fictional).",
    "adapter": "audio_v1",
    "adapter_config": {"region": "in"},
    "endpoint_url": "ws://mock-agent:8765/ws",
    "languages": ["kn-IN", "hi-IN", "en-IN"],
    "glass_box": True,
    "mandatory_disclosures": [
        {"id": "recording", "text": "recorded", "regex": "(record)", "within_turns": 2}
    ],
    "forbidden_phrases": [{"id": "threat", "text": "legal action", "regex": "(legal action)"}],
    "expected_tools": [
        {"name": "record_promise_to_pay", "description": "Save PTP", "args_schema": {"a": 1}}
    ],
    "bias_list": ["EMI", "UPI"],
    "max_call_seconds": 240,
}


async def _create(api: AsyncClient, tenant: Tenant, **overrides: Any) -> dict[str, Any]:
    response = await api.post("/api/v1/agents", json={**AGENT, **overrides}, headers=tenant.admin)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_all_fields_round_trip(api: AsyncClient, tenant: Tenant) -> None:
    created = await _create(api, tenant)
    assert created["archived"] is False and created["id"] and created["created_at"]
    fetched = (await api.get(f"/api/v1/agents/{created['id']}", headers=tenant.read)).json()
    for field, value in AGENT.items():
        assert fetched[field] == value, field
    assert fetched == created


async def test_crud_archive(api: AsyncClient, tenant: Tenant) -> None:
    created = await _create(api, tenant)
    agent_id = created["id"]
    patched = await api.patch(
        f"/api/v1/agents/{agent_id}",
        json={"glass_box": False, "max_call_seconds": 120, "bias_list": []},
        headers=tenant.admin,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert (
        body["glass_box"] is False and body["max_call_seconds"] == 120 and body["bias_list"] == []
    )
    assert body["name"] == AGENT["name"] and body["updated_at"] >= created["updated_at"]

    archived = await api.post(f"/api/v1/agents/{agent_id}/archive", headers=tenant.admin)
    assert archived.status_code == 200 and archived.json()["archived"] is True
    again = await api.post(f"/api/v1/agents/{agent_id}/archive", headers=tenant.admin)
    assert again.status_code == 200 and again.json()["archived"] is True

    listed = (await api.get("/api/v1/agents", headers=tenant.read)).json()
    assert listed["items"] == []
    with_archived = await api.get("/api/v1/agents?include_archived=true", headers=tenant.read)
    assert [a["id"] for a in with_archived.json()["items"]] == [agent_id]


async def test_duplicate_name_is_409(api: AsyncClient, tenant: Tenant) -> None:
    await _create(api, tenant)
    dup = await api.post("/api/v1/agents", json=AGENT, headers=tenant.admin)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "conflict"
    other = await _create(api, tenant, name="Other")
    clash = await api.patch(
        f"/api/v1/agents/{other['id']}", json={"name": AGENT["name"]}, headers=tenant.admin
    )
    assert clash.status_code == 409


async def test_unknown_agent_is_404_and_projects_are_isolated(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    missing = await api.get(f"/api/v1/agents/{uuid.uuid4()}", headers=tenant.read)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    patch = await api.patch(f"/api/v1/agents/{uuid.uuid4()}", json={}, headers=tenant.admin)
    assert patch.status_code == 404
    archive = await api.post(f"/api/v1/agents/{uuid.uuid4()}/archive", headers=tenant.admin)
    assert archive.status_code == 404

    created = await _create(api, tenant)
    # a key of another project can neither see nor change the agent
    url = f"/api/v1/agents/{created['id']}"
    assert (await api.get(url, headers=other_tenant.read)).status_code == 404
    assert (await api.patch(url, json={}, headers=other_tenant.admin)).status_code == 404
    assert (await api.get("/api/v1/agents", headers=other_tenant.read)).json()["items"] == []


async def test_read_key_cannot_write(api: AsyncClient, tenant: Tenant) -> None:
    response = await api.post("/api/v1/agents", json=AGENT, headers=tenant.read)
    assert response.status_code == 403
    assert response.json()["error"]["details"]["required"] == ["runs:write"]


async def test_validation_errors_are_400(api: AsyncClient, tenant: Tenant) -> None:
    bad = await api.post(
        "/api/v1/agents", json={**AGENT, "max_call_seconds": 5}, headers=tenant.admin
    )
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "validation_error"


async def test_pagination_walks_every_agent_once(api: AsyncClient, tenant: Tenant) -> None:
    ids = [(await _create(api, tenant, name=f"agent-{i}"))["id"] for i in range(5)]
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        url = "/api/v1/agents?limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = (await api.get(url, headers=tenant.read)).json()
        seen += [a["id"] for a in page["items"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert pages == 3 and sorted(seen) == sorted(ids) and len(set(seen)) == 5
    assert seen == ids[::-1]  # newest first


async def test_invalid_cursor_and_limit_are_400(api: AsyncClient, tenant: Tenant) -> None:
    assert (await api.get("/api/v1/agents?cursor=%%%", headers=tenant.read)).status_code == 400
    assert (await api.get("/api/v1/agents?cursor=abcd", headers=tenant.read)).status_code == 400
    assert (await api.get("/api/v1/agents?limit=500", headers=tenant.read)).status_code == 400
