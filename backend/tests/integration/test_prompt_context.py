"""The system prompt under test reaches scenario generation and the judge (prompt agents only)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.evaluation.pg_stores import PgEvaluatorStore
from tests.conftest import Tenant
from tests.integration.audit_support import transaction
from tests.integration.domain import API, build_world
from tests.integration.test_audit_same_rubric import make_simulation
from tests.integration.test_scenario_generation import request_events, run_handler
from tests.judge.scripted_llm import ScriptedScenarioLLM


async def add_version(
    pg: psycopg.AsyncConnection[Any], tenant: Tenant, agent_id: Any, version: int, prompt: str
) -> str:
    cur = await pg.execute(
        "INSERT INTO prompt_versions (project_id, agent_id, version, system_prompt, provider, "
        "model, temperature, content_hash) VALUES (%s, %s, %s, %s, 'openai', 'm', 0, %s) "
        "RETURNING id",
        (tenant.project_id, agent_id, version, prompt, uuid.uuid4().hex),
    )
    row = await cur.fetchone()
    assert row is not None
    return str(row[0])


async def generated_prompt(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
    agent_id: Any,
) -> str:
    accepted = await api.post(
        f"{API}/agents/{agent_id}/scenarios:generate", json={"count": 2}, headers=tenant.admin
    )
    env = (await request_events(session_factory, accepted.json()["draft_id"]))[0]
    provider = ScriptedScenarioLLM()
    await run_handler(pg, env, provider)
    return str(provider.requests[0].messages[0].content)


async def test_prompt_agent_brief_includes_system_prompt(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    world = await build_world(api, tenant)
    await add_version(pg, tenant, world.agent_id, 1, "OLD-PROMPT-TEXT")
    active = await add_version(pg, tenant, world.agent_id, 2, "NEW-PROMPT-TEXT")
    await pg.execute(
        "UPDATE agents SET adapter = 'prompt', adapter_config = %s WHERE id = %s",
        (Jsonb({"active_version_id": active}), world.agent_id),
    )
    prompt = await generated_prompt(api, tenant, session_factory, pg, world.agent_id)
    assert "System prompt under test:\nNEW-PROMPT-TEXT" in prompt
    assert "Outbound EMI reminder bot" in prompt and "OLD-PROMPT-TEXT" not in prompt


async def test_voice_agent_brief_unchanged(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    world = await build_world(api, tenant)
    await add_version(pg, tenant, world.agent_id, 1, "STRAY-PROMPT-TEXT")
    prompt = await generated_prompt(api, tenant, session_factory, pg, world.agent_id)
    assert "Outbound EMI reminder bot" in prompt
    assert "System prompt under test" not in prompt and "STRAY-PROMPT-TEXT" not in prompt


@pytest.mark.usefixtures("rubric")
async def test_judge_agent_info_includes_pinned_prompt(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    call_id, _, run_id = await make_simulation(api, tenant, database_url)
    async with transaction(database_url) as ctx:
        tx = ctx.tx
        cur = await tx.execute("SELECT agent_id FROM calls WHERE id = %s", (call_id,))
        row = await cur.fetchone()
        assert row is not None
        agent_id = row[0]
        pinned = await add_version(tx, tenant, agent_id, 1, "PINNED-PROMPT")
        active = await add_version(tx, tenant, agent_id, 2, "LATER-ACTIVE-PROMPT")
        await tx.execute(
            "UPDATE agents SET adapter = 'prompt', adapter_config = %s WHERE id = %s",
            (Jsonb({"active_version_id": active}), agent_id),
        )
        await tx.execute(
            "UPDATE test_runs SET agent_snapshot = %s WHERE id = %s",
            (Jsonb({"adapter_config": {"active_version_id": pinned}}), run_id),
        )
        snapshot = await PgEvaluatorStore(tx).load_snapshot(uuid.UUID(call_id))
    assert snapshot is not None
    assert "System prompt under test:\nPINNED-PROMPT" in snapshot.agent.description
    assert "LATER-ACTIVE-PROMPT" not in snapshot.agent.description
