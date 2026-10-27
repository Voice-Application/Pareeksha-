"""``POST /agents/{id}/test-connection`` against the real app, real Postgres and a real socket."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

from tests.conftest import Tenant
from tests.integration.mock_agent_harness import FakeSpeech, running_agent


async def _agent(api: AsyncClient, tenant: Tenant, endpoint: str, **over: Any) -> str:
    body = {
        "name": f"agent-{uuid.uuid4().hex[:6]}",
        "adapter": "audio_v1",
        "endpoint_url": endpoint,
        "languages": ["en-IN"],
        **over,
    }
    response = await api.post("/api/v1/agents", json=body, headers=tenant.admin)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_reports_first_audio_and_glass_box_from_the_mock_agent(
    api: AsyncClient, tenant: Tenant
) -> None:
    async with running_agent(FakeSpeech([])) as addr:
        agent_id = await _agent(api, tenant, f"ws://{addr}/call")
        response = await api.post(
            f"/api/v1/agents/{agent_id}/test-connection", headers=tenant.admin
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True and body["protocol"] == "pareeksha-audio-v1"
    assert body["glass_box_messages_seen"] is True
    assert 0 <= body["first_audio_ms"] < 10_000


async def test_unreachable_agent_is_reported_not_an_error_status(
    api: AsyncClient, tenant: Tenant
) -> None:
    agent_id = await _agent(api, tenant, "ws://127.0.0.1:1/call")
    response = await api.post(f"/api/v1/agents/{agent_id}/test-connection", headers=tenant.admin)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and body["error"] == "connect_failed" and body["detail"]


async def test_adapter_that_is_not_installed_is_reported(api: AsyncClient, tenant: Tenant) -> None:
    agent_id = await _agent(api, tenant, "wss://bot.example/ws", adapter="livekit")
    response = await api.post(f"/api/v1/agents/{agent_id}/test-connection", headers=tenant.admin)
    assert response.json()["error"] == "adapter_unavailable"


async def test_unknown_agent_other_projects_agents_and_read_only_keys(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    missing = await api.post(f"/api/v1/agents/{uuid.uuid4()}/test-connection", headers=tenant.admin)
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"

    agent_id = await _agent(api, tenant, "ws://127.0.0.1:1/call")
    foreign = await api.post(
        f"/api/v1/agents/{agent_id}/test-connection", headers=other_tenant.admin
    )
    assert foreign.status_code == 404

    read_only = await api.post(f"/api/v1/agents/{agent_id}/test-connection", headers=tenant.read)
    assert read_only.status_code == 403
