"""Scenario generation end to end: POST -> outbox -> the ``generator`` handler -> poll the draft.

The handler runs against the real database with a scripted model; the live DeepSeek run is in
proof/API-05. Drafts are never saved as scenarios (FR-SC-2: the user reviews first)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.events.consumer import Ctx
from pareeksha.events.schemas import AnyEnvelope, ScenarioGenerateRequested
from pareeksha.llm.base import LLMPermanentError, LLMRetryableError
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMConfigError, LLMSettings
from pareeksha.workers.generator import handle_generate_requested
from tests.conftest import Tenant
from tests.integration.domain import API, build_world, outbox_for
from tests.judge.scripted_llm import ScriptedScenarioLLM

GENERATE = {"count": 10, "mix": {"happy_path": 3, "edge_case": 4, "adversarial": 3}}


def llm_for(provider: ScriptedScenarioLLM) -> Any:
    def make(sink: Any) -> LLMClient:
        settings = LLMSettings(deepseek_api_key="k", deepseek_caller_model="pinned")
        return LLMClient(provider, settings, usage_sink=sink)

    return make


async def request_events(
    factory: async_sessionmaker[AsyncSession], draft_id: str
) -> list[AnyEnvelope]:
    return await outbox_for(factory, "draft_id", draft_id)


async def run_handler(
    pg: psycopg.AsyncConnection[Any],
    env: AnyEnvelope,
    provider: ScriptedScenarioLLM,
    attempt: int = 1,
) -> None:
    assert isinstance(env.payload, ScenarioGenerateRequested)
    ctx = Ctx(
        tx=pg, group="generator", topic=env.topic.value, partition=0, offset=0, attempt=attempt
    )
    async with pg.transaction():
        await handle_generate_requested(env, ctx, llm_for(provider))  # type: ignore[arg-type]


async def test_generate_then_poll_until_ready(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    world = await build_world(api, tenant)
    url = f"{API}/agents/{world.agent_id}/scenarios:generate"
    accepted = await api.post(url, json=GENERATE, headers=tenant.admin)
    assert accepted.status_code == 202, accepted.text
    draft_id = accepted.json()["draft_id"]

    pending = (await api.get(f"{API}/scenario-drafts/{draft_id}", headers=tenant.read)).json()
    assert (pending["status"], pending["drafts"], pending["error"]) == ("pending", [], None)
    assert pending["request"] == GENERATE and pending["agent_id"] == str(world.agent_id)

    events = await request_events(session_factory, draft_id)
    assert len(events) == 1 and events[0].topic.value == "pareeksha.scenario.generate.requested.v1"
    assert events[0].partition_key() == str(world.agent_id)
    payload = events[0].payload
    assert isinstance(payload, ScenarioGenerateRequested)
    assert (payload.count, payload.mix) == (10, GENERATE["mix"])

    provider = ScriptedScenarioLLM()
    await run_handler(pg, events[0], provider)
    ready = (await api.get(f"{API}/scenario-drafts/{draft_id}", headers=tenant.read)).json()
    assert ready["status"] == "ready" and ready["error"] is None
    assert len(ready["drafts"]) == 10
    assert {d["title"] for d in ready["drafts"]} and all(
        d["max_turns"] == 12 for d in ready["drafts"]
    )
    # the model saw the agent's description and the titles of its existing scenarios
    prompt = provider.requests[0].messages[0].content
    assert "Outbound EMI reminder bot" in prompt and "already paid, wants confirmation" in prompt

    saved = (await api.get(f"{API}/scenarios", headers=tenant.read)).json()["items"]
    assert len(saved) == 1  # only the world's own scenario: drafts are not saved
    usage = await (
        await pg.execute(
            "SELECT count(*), sum(units) FROM api_usage WHERE operation = 'llm_scenario_gen'"
        )
    ).fetchone()
    assert usage is not None and usage[0] >= 1 and usage[1] > 0

    calls_before = len(provider.requests)
    await run_handler(pg, events[0], provider)  # redelivery: the stored answer stands
    assert len(provider.requests) == calls_before


async def test_bulk_save_of_reviewed_drafts_uses_the_existing_endpoint(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    world = await build_world(api, tenant)
    accepted = await api.post(
        f"{API}/agents/{world.agent_id}/scenarios:generate", json={"count": 2}, headers=tenant.admin
    )
    draft_id = accepted.json()["draft_id"]
    await run_handler(
        pg, (await request_events(session_factory, draft_id))[0], ScriptedScenarioLLM()
    )
    drafts = (await api.get(f"{API}/scenario-drafts/{draft_id}", headers=tenant.read)).json()[
        "drafts"
    ]
    assert len(drafts) == 2
    bulk = await api.post(
        f"{API}/scenarios:bulk",
        json={"scenarios": drafts, "source": "generated"},
        headers=tenant.admin,
    )
    assert bulk.status_code == 201, bulk.text
    assert [s["source"] for s in bulk.json()["items"]] == ["generated", "generated"]


async def test_request_validation_and_isolation(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    world = await build_world(api, tenant)
    url = f"{API}/agents/{world.agent_id}/scenarios:generate"
    bad_total = await api.post(
        url, json={"count": 10, "mix": {"happy_path": 3}}, headers=tenant.admin
    )
    assert bad_total.status_code == 400 and "add up" in bad_total.json()["error"]["message"]
    bad_key = await api.post(url, json={"count": 1, "mix": {"chaos": 1}}, headers=tenant.admin)
    assert bad_key.status_code == 400
    assert (await api.post(url, json={"count": 0}, headers=tenant.admin)).status_code == 400
    assert (await api.post(url, json={"count": 51}, headers=tenant.admin)).status_code == 400
    assert (await api.post(url, json={"count": 2}, headers=tenant.read)).status_code == 403
    assert (await api.post(url, json={"count": 2}, headers=other_tenant.admin)).status_code == 404
    ghost = await api.post(
        f"{API}/agents/{uuid.uuid4()}/scenarios:generate", json={"count": 2}, headers=tenant.admin
    )
    assert ghost.status_code == 404

    draft = (await api.post(url, json={"count": 2}, headers=tenant.admin)).json()["draft_id"]
    assert (
        await api.get(f"{API}/scenario-drafts/{draft}", headers=other_tenant.read)
    ).status_code == 404
    assert (
        await api.get(f"{API}/scenario-drafts/{uuid.uuid4()}", headers=tenant.read)
    ).status_code == 404


@pytest.mark.parametrize(
    ("error", "expected_detail"),
    [
        (LLMPermanentError("bad key"), "bad key"),
        (LLMConfigError("LLM_PROVIDER=deepseek but its API key is not set"), "API key is not set"),
    ],
)
async def test_permanent_llm_errors_fail_the_draft_without_retrying(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
    error: Exception,
    expected_detail: str,
) -> None:
    world = await build_world(api, tenant)
    draft_id = (
        await api.post(
            f"{API}/agents/{world.agent_id}/scenarios:generate",
            json={"count": 2},
            headers=tenant.admin,
        )
    ).json()["draft_id"]
    env = (await request_events(session_factory, draft_id))[0]
    await run_handler(pg, env, ScriptedScenarioLLM(fail_with=error))
    failed = (await api.get(f"{API}/scenario-drafts/{draft_id}", headers=tenant.read)).json()
    assert failed["status"] == "failed" and expected_detail in failed["error"]
    assert failed["drafts"] == []


async def test_a_model_that_keeps_failing_the_checks_marks_the_draft_failed(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    world = await build_world(api, tenant)
    draft_id = (
        await api.post(
            f"{API}/agents/{world.agent_id}/scenarios:generate",
            json={"count": 3},
            headers=tenant.admin,
        )
    ).json()["draft_id"]
    env = (await request_events(session_factory, draft_id))[0]
    await run_handler(pg, env, ScriptedScenarioLLM(lambda call, items: items[:1]))
    failed = (await api.get(f"{API}/scenario-drafts/{draft_id}", headers=tenant.read)).json()
    assert failed["status"] == "failed" and "expected exactly 3" in failed["error"]


async def test_transient_llm_errors_retry_until_the_last_attempt_then_fail_the_draft(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    world = await build_world(api, tenant)
    draft_id = (
        await api.post(
            f"{API}/agents/{world.agent_id}/scenarios:generate",
            json={"count": 2},
            headers=tenant.admin,
        )
    ).json()["draft_id"]
    env = (await request_events(session_factory, draft_id))[0]
    flaky = ScriptedScenarioLLM(fail_with=LLMRetryableError("503 from provider"))
    with pytest.raises(LLMRetryableError):  # the framework retries this one
        await run_handler(pg, env, flaky, attempt=1)
    still = (await api.get(f"{API}/scenario-drafts/{draft_id}", headers=tenant.read)).json()
    assert still["status"] == "pending"
    await run_handler(pg, env, flaky, attempt=3)  # last attempt: report instead of dead-lettering
    done = (await api.get(f"{API}/scenario-drafts/{draft_id}", headers=tenant.read)).json()
    assert done["status"] == "failed" and "LLM unavailable" in done["error"]


async def test_handler_tolerates_a_deleted_agent_or_draft(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    world = await build_world(api, tenant)
    draft_id = (
        await api.post(
            f"{API}/agents/{world.agent_id}/scenarios:generate",
            json={"count": 2},
            headers=tenant.admin,
        )
    ).json()["draft_id"]
    env = (await request_events(session_factory, draft_id))[0]
    ghost = env.model_copy(
        update={"payload": env.payload.model_copy(update={"draft_id": uuid.uuid4()})}
    )
    provider = ScriptedScenarioLLM()
    await run_handler(pg, ghost, provider)  # no such draft: nothing to do
    assert provider.requests == []
    await pg.execute("DELETE FROM agents WHERE id = %s", (world.agent_id,))  # cascades the draft
    await run_handler(pg, env, provider)
    assert provider.requests == []
