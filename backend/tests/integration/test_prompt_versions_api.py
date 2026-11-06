"""Prompt agents: versions, write-only provider secrets, test-connection (real Postgres)."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.agent_llm import AgentLLMError, AgentMessage, ChatReply, ToolSpec
from pareeksha.db.models import Agents, TestRuns
from tests.conftest import Tenant
from tests.integration.runs_support import make_fixture

API = "/api/v1"
KEY = "sk-test-secret"

VERSION: dict[str, Any] = {
    "system_prompt": "You are a refund bot.",
    "provider": "openai",
    "model": "gpt-4o-mini",
    "tools": [
        {
            "name": "refund",
            "description": "Refund an order",
            "parameters": {"type": "object", "properties": {"order": {"type": "string"}}},
        }
    ],
}


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("AGENT_LLM_ALLOW_PRIVATE_URLS", raising=False)


async def _agent(api: AsyncClient, tenant: Tenant, **extra: Any) -> dict[str, Any]:
    body = {"name": f"prompt-{uuid.uuid4().hex[:6]}", "adapter": "prompt", **extra}
    response = await api.post(f"{API}/agents", json=body, headers=tenant.admin)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def _version(
    api: AsyncClient, tenant: Tenant, agent_id: str, **overrides: Any
) -> dict[str, Any]:
    response = await api.post(
        f"{API}/agents/{agent_id}/prompt-versions",
        json={**VERSION, **overrides},
        headers=tenant.admin,
    )
    assert response.status_code in (200, 201), response.text
    created: dict[str, Any] = response.json()
    return created


async def test_create_prompt_agent_without_endpoint(api: AsyncClient, tenant: Tenant) -> None:
    agent = await _agent(api, tenant)
    assert agent["endpoint_url"] == f"prompt://{agent['id']}"
    assert agent["adapter"] == "prompt" and agent["has_adapter_secrets"] is False
    voice = await api.post(f"{API}/agents", json={"name": "voice"}, headers=tenant.admin)
    assert voice.status_code == 400  # endpoint_url is only optional for prompt agents


async def test_create_version_sets_active_and_expected_tools(
    api: AsyncClient, tenant: Tenant
) -> None:
    agent = await _agent(api, tenant)
    created = await api.post(
        f"{API}/agents/{agent['id']}/prompt-versions", json=VERSION, headers=tenant.admin
    )
    assert created.status_code == 201
    version = created.json()
    assert version["version"] == 1 and version["agent_id"] == agent["id"]
    assert len(version["content_hash"]) == 64
    fetched = (await api.get(f"{API}/agents/{agent['id']}", headers=tenant.read)).json()
    assert fetched["adapter_config"]["active_version_id"] == version["id"]
    assert fetched["expected_tools"] == [
        {
            "name": "refund",
            "description": "Refund an order",
            "args_schema": VERSION["tools"][0]["parameters"],
        }
    ]


async def test_identical_version_is_not_duplicated(api: AsyncClient, tenant: Tenant) -> None:
    agent = await _agent(api, tenant)
    first = await _version(api, tenant, agent["id"])
    again = await api.post(
        f"{API}/agents/{agent['id']}/prompt-versions",
        json={**VERSION, "note": "only the note differs"},
        headers=tenant.admin,
    )
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    listed = await api.get(f"{API}/agents/{agent['id']}/prompt-versions", headers=tenant.read)
    assert len(listed.json()) == 1


async def test_versions_listed_newest_first(api: AsyncClient, tenant: Tenant) -> None:
    agent = await _agent(api, tenant)
    for i in range(3):
        await _version(api, tenant, agent["id"], system_prompt=f"prompt {i}")
    listed = await api.get(f"{API}/agents/{agent['id']}/prompt-versions", headers=tenant.read)
    assert [v["version"] for v in listed.json()] == [3, 2, 1]
    one = await api.get(f"{API}/agents/{agent['id']}/prompt-versions/2", headers=tenant.read)
    assert one.json()["system_prompt"] == "prompt 1"
    missing = await api.get(f"{API}/agents/{agent['id']}/prompt-versions/9", headers=tenant.read)
    assert missing.status_code == 404


async def test_activate_older_version(api: AsyncClient, tenant: Tenant) -> None:
    agent = await _agent(api, tenant)
    first = await _version(api, tenant, agent["id"])
    await _version(api, tenant, agent["id"], tools=[])
    assert (await api.get(f"{API}/agents/{agent['id']}", headers=tenant.read)).json()[
        "expected_tools"
    ] == []
    activated = await api.post(
        f"{API}/agents/{agent['id']}/prompt-versions/1/activate", headers=tenant.admin
    )
    assert activated.status_code == 200 and activated.json()["id"] == first["id"]
    fetched = (await api.get(f"{API}/agents/{agent['id']}", headers=tenant.read)).json()
    assert fetched["adapter_config"]["active_version_id"] == first["id"]
    assert [t["name"] for t in fetched["expected_tools"]] == ["refund"]


async def test_other_tenant_gets_404(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    agent = await _agent(api, tenant)
    await _version(api, tenant, agent["id"])
    base = f"{API}/agents/{agent['id']}/prompt-versions"
    assert (await api.get(base, headers=other_tenant.read)).status_code == 404
    assert (await api.get(f"{base}/1", headers=other_tenant.read)).status_code == 404
    assert (await api.post(base, json=VERSION, headers=other_tenant.admin)).status_code == 404
    assert (await api.post(f"{base}/1/activate", headers=other_tenant.admin)).status_code == 404


async def test_versions_rejected_for_voice_agent(api: AsyncClient, tenant: Tenant) -> None:
    voice = await api.post(
        f"{API}/agents",
        json={"name": "voice", "endpoint_url": "ws://mock-agent:8765/ws"},
        headers=tenant.admin,
    )
    base = f"{API}/agents/{voice.json()['id']}/prompt-versions"
    for response in (
        await api.post(base, json=VERSION, headers=tenant.admin),
        await api.get(base, headers=tenant.read),
        await api.post(f"{base}/1/activate", headers=tenant.admin),
    ):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "not_a_prompt_agent"


async def test_api_key_never_returned(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    agent = await _agent(api, tenant, adapter_secrets={"api_key": KEY})
    assert agent["has_adapter_secrets"] is True and KEY not in json.dumps(agent)
    version = await _version(api, tenant, agent["id"])
    bodies = [
        (await api.get(f"{API}/agents/{agent['id']}", headers=tenant.read)).text,
        (await api.get(f"{API}/agents", headers=tenant.read)).text,
        (await api.get(f"{API}/agents/{agent['id']}/prompt-versions", headers=tenant.read)).text,
        json.dumps(version),
    ]
    patched = await api.patch(
        f"{API}/agents/{agent['id']}", json={"description": "x"}, headers=tenant.admin
    )
    bodies.append(patched.text)
    assert patched.json()["has_adapter_secrets"] is True  # untouched by an unrelated PATCH

    fx = await make_fixture(api, tenant, scenarios=1, personas=1, profiles=1)
    run = await api.post(f"{API}/runs", json=fx.body(agent_id=agent["id"]), headers=tenant.admin)
    assert run.status_code == 201, run.text
    bodies.append(run.text)
    async with session_factory() as session:
        stored = await session.get(Agents, uuid.UUID(agent["id"]))
        assert stored is not None and stored.adapter_secrets_encrypted
        assert KEY.encode() not in stored.adapter_secrets_encrypted  # encrypted at rest
        snapshot = await session.get(TestRuns, uuid.UUID(run.json()["id"]))
        assert snapshot is not None
        bodies.append(json.dumps(snapshot.agent_snapshot))
    assert all(KEY not in body for body in bodies)

    cleared = await api.patch(
        f"{API}/agents/{agent['id']}", json={"adapter_secrets": {}}, headers=tenant.admin
    )
    assert cleared.json()["has_adapter_secrets"] is False


async def test_private_base_url_rejected(api: AsyncClient, tenant: Tenant) -> None:
    agent = await _agent(api, tenant)
    for url in ("http://169.254.169.254/", "http://127.0.0.1:8080"):
        response = await api.post(
            f"{API}/agents/{agent['id']}/prompt-versions",
            json={**VERSION, "provider": "openai_compatible", "base_url": url},
            headers=tenant.admin,
        )
        assert response.status_code == 422, url
        assert response.json()["error"]["code"] == "base_url_not_allowed"


async def test_private_base_url_allowed_with_flag(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_LLM_ALLOW_PRIVATE_URLS", "true")
    agent = await _agent(api, tenant)
    created = await api.post(
        f"{API}/agents/{agent['id']}/prompt-versions",
        json={**VERSION, "provider": "ollama", "base_url": "http://127.0.0.1:11434/v1"},
        headers=tenant.admin,
    )
    assert created.status_code == 201


async def test_run_refused_without_version(api: AsyncClient, tenant: Tenant) -> None:
    agent = await _agent(api, tenant)
    fx = await make_fixture(api, tenant, scenarios=1, personas=1, profiles=1)
    response = await api.post(
        f"{API}/runs", json=fx.body(agent_id=agent["id"]), headers=tenant.admin
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "prompt_agent_has_no_version"


class _FakeProvider:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.messages: Sequence[AgentMessage] = ()

    async def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        model: str,
        temperature: float,
        timeout_s: float = 60.0,
    ) -> ChatReply:
        self.messages = messages
        if self.error:
            raise self.error
        assert not tools and model == "gpt-4o-mini"
        return ChatReply(text="Hi", tool_calls=(), input_tokens=3, output_tokens=1, latency_ms=42)


async def test_test_connection_for_prompt_agent(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _agent(api, tenant, adapter_secrets={"api_key": KEY})
    url = f"{API}/agents/{agent['id']}/test-connection"
    no_version = await api.post(url, headers=tenant.admin)
    assert no_version.json()["ok"] is False and no_version.json()["error"] == "no_active_version"

    await _version(api, tenant, agent["id"])
    fake = _FakeProvider()
    seen: dict[str, Any] = {}

    def build(provider: str, *, api_key: str | None, base_url: str | None = None) -> _FakeProvider:
        seen.update(provider=provider, api_key=api_key)
        return fake

    monkeypatch.setattr("pareeksha.api.routers.agents.build_chat_provider", build)
    ok = await api.post(url, headers=tenant.admin)
    assert ok.json()["ok"] is True and ok.json()["first_audio_ms"] == 42
    assert seen == {"provider": "openai", "api_key": KEY}
    assert [m.role for m in fake.messages] == ["system", "user"]

    fake.error = AgentLLMError("provider returned 401", status=401, retryable=False)
    failed = await api.post(url, headers=tenant.admin)
    assert failed.json()["ok"] is False and failed.json()["error"] == "provider_error"
    assert KEY not in failed.text
