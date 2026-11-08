"""A tenant can never run, read or compare another tenant's prompt version; secrets stay secret."""

from __future__ import annotations

import functools
import uuid
from typing import Any

import httpx
import psycopg
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.agent_llm import base
from pareeksha.evaluation.pg_stores import PgEvaluatorStore
from pareeksha.events.schemas import CallRequested
from pareeksha.integrations.ssrf import safe_request
from pareeksha.simulation import store
from tests.conftest import Tenant
from tests.integration.api04_support import new_rubric, seed_run
from tests.integration.audit_support import transaction
from tests.integration.domain import build_world
from tests.integration.runs_support import API, make_fixture, plan_in_db
from tests.integration.test_audit_same_rubric import make_simulation
from tests.integration.test_prompt_context import add_version, generated_prompt
from tests.integration.test_prompt_versions_api import KEY, VERSION, _agent, _version

SECRET_PROMPT = "TENANT-A-SECRET-PROMPT"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("AGENT_LLM_ALLOW_PRIVATE_URLS", raising=False)


async def _foreign_version(
    pg: psycopg.AsyncConnection[Any], owner: Tenant, api: AsyncClient
) -> str:
    """A version (with a recognisable prompt) belonging to another tenant's agent."""
    agent = await _agent(api, owner)
    return await add_version(pg, owner, uuid.UUID(agent["id"]), 1, SECRET_PROMPT)


async def _point_at(pg: psycopg.AsyncConnection[Any], agent_id: str, version_id: str) -> None:
    await pg.execute(
        "UPDATE agents SET adapter = 'prompt', adapter_config = %s WHERE id = %s",
        (Jsonb({"active_version_id": version_id}), agent_id),
    )


# -- the server owns active_version_id ------------------------------------------------------


async def test_client_cannot_set_active_version_id(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    """``active_version_id`` sent on create or PATCH is dropped; the server keeps its own."""
    foreign = await _version(api, other_tenant, (await _agent(api, other_tenant))["id"])
    mine = await _agent(api, tenant, adapter_config={"active_version_id": foreign["id"], "k": 1})
    assert mine["adapter_config"] == {"k": 1}  # stripped on create
    own = await _version(api, tenant, mine["id"])

    url = f"{API}/agents/{mine['id']}"
    patched = await api.patch(
        url,
        json={"adapter_config": {"active_version_id": foreign["id"], "k": 2}},
        headers=tenant.admin,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["adapter_config"] == {"k": 2, "active_version_id": own["id"]}
    cleared = await api.patch(url, json={"adapter_config": {}}, headers=tenant.admin)
    assert cleared.json()["adapter_config"] == {"active_version_id": own["id"]}


async def test_patch_cannot_turn_prompt_agent_into_endpointless_voice_agent(
    api: AsyncClient, tenant: Tenant
) -> None:
    """Leaving the prompt adapter needs an endpoint; a prompt agent's endpoint cannot be set."""
    agent = await _agent(api, tenant)
    url = f"{API}/agents/{agent['id']}"
    refused = await api.patch(url, json={"adapter": "audio_v1"}, headers=tenant.admin)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "endpoint_url_required"
    to_voice = await api.patch(
        url, json={"adapter": "audio_v1", "endpoint_url": "ws://agent/ws"}, headers=tenant.admin
    )
    assert (to_voice.json()["adapter"], to_voice.json()["endpoint_url"]) == (
        "audio_v1",
        "ws://agent/ws",
    )
    back = await api.patch(url, json={"adapter": "prompt"}, headers=tenant.admin)
    assert back.json()["endpoint_url"] == f"prompt://{agent['id']}"
    # a prompt agent has no endpoint of its own to change
    still = await api.patch(url, json={"endpoint_url": "ws://evil/ws"}, headers=tenant.admin)
    assert still.json()["endpoint_url"] == f"prompt://{agent['id']}"


# -- a foreign version id planted in the database is still unusable ---------------------------


async def test_run_refused_for_foreign_version(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, pg: psycopg.AsyncConnection[Any]
) -> None:
    """A run is refused when the agent points at another tenant's version."""
    foreign = await _foreign_version(pg, other_tenant, api)
    fx = await make_fixture(api, tenant, 1, 1, 1)
    await _point_at(pg, fx.agent_id, foreign)
    response = await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "prompt_agent_has_no_version"


async def test_test_connection_ignores_foreign_version(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, pg: psycopg.AsyncConnection[Any]
) -> None:
    """Test-connection treats another tenant's version as no active version."""
    foreign = await _foreign_version(pg, other_tenant, api)
    agent = await _agent(api, tenant, adapter_secrets={"api_key": KEY})
    await _point_at(pg, agent["id"], foreign)
    response = await api.post(f"{API}/agents/{agent['id']}/test-connection", headers=tenant.admin)
    assert response.json()["error"] == "no_active_version"


async def test_read_spec_ignores_foreign_pinned_version(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    database_url: str,
    pg: psycopg.AsyncConnection[Any],
) -> None:
    """``read_spec`` loads the run's own pinned version but never another tenant's."""
    fx = await make_fixture(api, tenant, 1, 1, 1)
    own = await add_version(pg, tenant, uuid.UUID(fx.agent_id), 1, "my prompt")
    await _point_at(pg, fx.agent_id, own)
    created = await api.post(f"{API}/runs", json=fx.body(), headers=tenant.admin)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    req = next(
        o.payload
        for o in await plan_in_db(database_url, run_id)
        if isinstance(o.payload, CallRequested)
    )
    spec, _ = await store.read_spec(pg, req)
    assert spec.agent.adapter_config["prompt_version"]["system_prompt"] == "my prompt"

    foreign = await _foreign_version(pg, other_tenant, api)
    await _point_at(pg, fx.agent_id, foreign)  # agent row and the run's pinned snapshot
    await pg.execute(
        "UPDATE test_runs SET agent_snapshot = %s WHERE id = %s",
        (Jsonb({"adapter_config": {"active_version_id": foreign}}), run_id),
    )
    spec, _ = await store.read_spec(pg, req)
    assert "prompt_version" not in spec.agent.adapter_config
    assert SECRET_PROMPT not in repr(spec)


async def test_compare_ignores_foreign_version(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    """Compare resolves a run's own pinned version number and reports a foreign one as null."""
    fx = await make_fixture(api, tenant, scenarios=1, personas=1, profiles=1)
    rubric = await new_rubric(session_factory)
    base_run = await seed_run(
        api, session_factory, tenant, fx=fx, rubric_id=rubric, scores=[(80, True)]
    )
    head_run = await seed_run(
        api, session_factory, tenant, fx=fx, rubric_id=rubric, scores=[(90, True)]
    )
    own = await add_version(pg, tenant, uuid.UUID(fx.agent_id), 7, "mine")
    foreign = await _foreign_version(pg, other_tenant, api)

    async def pin(run_id: Any, version_id: str) -> None:
        await pg.execute(
            "UPDATE test_runs SET agent_snapshot = %s WHERE id = %s",
            (
                Jsonb({"adapter": "prompt", "adapter_config": {"active_version_id": version_id}}),
                run_id,
            ),
        )

    await pin(base_run.run_id, own)
    await pin(head_run.run_id, foreign)
    response = await api.get(
        f"{API}/runs/compare",
        params={"base": str(base_run.run_id), "head": str(head_run.run_id)},
        headers=tenant.read,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["base_prompt_version"] == 7  # own version resolves
    assert body["head_prompt_version"] is None  # a foreign one does not


async def test_scenario_generation_ignores_foreign_version(
    api: AsyncClient,
    tenant: Tenant,
    other_tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    """Scenario generation never puts another tenant's prompt in the brief."""
    world = await build_world(api, tenant)
    foreign = await _foreign_version(pg, other_tenant, api)
    await _point_at(pg, str(world.agent_id), foreign)
    prompt = await generated_prompt(api, tenant, session_factory, pg, world.agent_id)
    assert SECRET_PROMPT not in prompt


@pytest.mark.usefixtures("rubric")
async def test_judge_snapshot_ignores_foreign_version(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, database_url: str
) -> None:
    """The judge's agent description never includes another tenant's prompt."""
    call_id, _, run_id = await make_simulation(api, tenant, database_url)
    async with transaction(database_url) as ctx:
        tx = ctx.tx
        cur = await tx.execute("SELECT agent_id FROM calls WHERE id = %s", (call_id,))
        row = await cur.fetchone()
        assert row is not None
        foreign = await _foreign_version(tx, other_tenant, api)
        await _point_at(tx, str(row[0]), foreign)
        await tx.execute(
            "UPDATE test_runs SET agent_snapshot = %s WHERE id = %s",
            (Jsonb({"adapter_config": {"active_version_id": foreign}}), run_id),
        )
        snapshot = await PgEvaluatorStore(tx).load_snapshot(uuid.UUID(call_id))
    assert snapshot is not None and SECRET_PROMPT not in snapshot.agent.description


# -- test-connection goes through the SSRF guard -----------------------------------------------


def _guard(monkeypatch: pytest.MonkeyPatch, ip: str) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    async def resolver(host: str, port: int) -> list[str]:
        return [ip]

    monkeypatch.setattr(
        base,
        "safe_request",
        functools.partial(safe_request, resolver=resolver, transport=httpx.MockTransport(handler)),
    )
    return seen


async def test_test_connection_blocks_host_that_rebinds_to_loopback(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host that resolves to loopback at request time is blocked; a public IP is called."""
    # the name passes the create-time check (it would resolve publicly then) ...
    monkeypatch.setattr(
        "pareeksha.api.routers.prompt_versions.check_base_url", lambda *a, **k: None
    )
    agent = await _agent(api, tenant, adapter_secrets={"api_key": KEY})
    await _version(
        api,
        tenant,
        agent["id"],
        provider="openai_compatible",
        base_url="https://llm.example.test/v1",
    )
    # ... but resolves to loopback when the request is made
    seen = _guard(monkeypatch, "127.0.0.1")
    response = await api.post(f"{API}/agents/{agent['id']}/test-connection", headers=tenant.admin)
    result = response.json()
    assert result["ok"] is False and result["error"] == "provider_error"
    assert "non-public" in result["detail"] and KEY not in response.text
    assert seen == []

    seen = _guard(monkeypatch, "8.8.8.8")  # control: a public answer is called, pinned to the IP
    ok = await api.post(f"{API}/agents/{agent['id']}/test-connection", headers=tenant.admin)
    assert ok.json()["ok"] is True and seen[0].url.host == "8.8.8.8"


async def test_test_connection_blocks_ollama_default_without_flag(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plain-http Ollama default is refused unless private URLs are allowed."""
    agent = await _agent(api, tenant)
    await _version(api, tenant, agent["id"], provider="ollama", model="llama3")
    seen = _guard(monkeypatch, "8.8.8.8")
    response = await api.post(f"{API}/agents/{agent['id']}/test-connection", headers=tenant.admin)
    assert response.json()["ok"] is False and response.json()["error"] == "provider_error"
    assert "https" in response.json()["detail"] and seen == []


async def test_version_create_requires_https_unless_private_allowed(
    api: AsyncClient, tenant: Tenant
) -> None:
    """A plain-http base URL is rejected on create while private URLs are not allowed."""
    agent = await _agent(api, tenant)
    plain = await api.post(
        f"{API}/agents/{agent['id']}/prompt-versions",
        json={**VERSION, "provider": "openai_compatible", "base_url": "http://8.8.8.8/v1"},
        headers=tenant.admin,
    )
    assert plain.status_code == 422 and plain.json()["error"]["code"] == "base_url_not_allowed"


# -- validation errors never echo secrets ------------------------------------------------------


@pytest.mark.parametrize(
    "secrets", [{"api_key": 123456789}, "sk-live-recognisable-4242", ["sk-live-recognisable-4242"]]
)
async def test_invalid_adapter_secrets_are_not_echoed(
    api: AsyncClient, tenant: Tenant, secrets: Any
) -> None:
    """A 400 for malformed ``adapter_secrets`` never repeats the submitted values."""
    created = await _agent(api, tenant)
    body = {"name": "s", "adapter": "prompt", "adapter_secrets": secrets}
    for response in (
        await api.post(f"{API}/agents", json=body, headers=tenant.admin),
        await api.patch(f"{API}/agents/{created['id']}", json=body, headers=tenant.admin),
    ):
        assert response.status_code == 400, response.text
        assert "123456789" not in response.text and "recognisable" not in response.text
