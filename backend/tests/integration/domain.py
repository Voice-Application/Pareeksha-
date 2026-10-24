"""Builders for rows that the simulator / auditor / evaluator write (not API-created), so API
tests can start from "a call that was evaluated". Everything goes through the real tables."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.db.models import (
    Calls,
    Evaluations,
    OutboxEvents,
    RegressionTests,
    RubricVersions,
    RunItems,
    TestRuns,
    Turns,
)
from pareeksha.evaluation.rubric import DIMENSION_KEYS, RUBRIC_VERSION
from pareeksha.events.schemas import AnyEnvelope, parse_envelope
from tests.conftest import Tenant
from tests.integration.test_personas_api import PERSONA
from tests.integration.test_scenarios_api import SCENARIO

API = "/api/v1"


@dataclass
class World:
    tenant: Tenant
    agent_id: uuid.UUID
    scenario_id: uuid.UUID
    persona_id: uuid.UUID
    noise_id: uuid.UUID


async def build_world(api: AsyncClient, tenant: Tenant, **scenario: Any) -> World:
    tag = uuid.uuid4().hex[:6]
    agent = await api.post(
        f"{API}/agents",
        json={
            "name": f"EMI Bot {tag}",
            "description": "Outbound EMI reminder bot (fictional lender).",
            "endpoint_url": "ws://mock-agent:8765/ws",
            "languages": ["kn-IN", "en-IN"],
            "expected_tools": [{"name": "record_utr", "description": "Save the UTR"}],
        },
        headers=tenant.admin,
    )
    scenario_row = await api.post(
        f"{API}/scenarios",
        json={**SCENARIO, "agent_id": agent.json()["id"], **scenario},
        headers=tenant.admin,
    )
    persona = await api.post(
        f"{API}/personas", json={**PERSONA, "name": f"Persona {tag}"}, headers=tenant.admin
    )
    noise = await api.post(
        f"{API}/noise-profiles",
        json={"name": f"clean-{tag}"},
        headers=tenant.admin,
    )
    for response in (agent, scenario_row, persona, noise):
        assert response.status_code == 201, response.text
    return World(
        tenant,
        uuid.UUID(agent.json()["id"]),
        uuid.UUID(scenario_row.json()["id"]),
        uuid.UUID(persona.json()["id"]),
        uuid.UUID(noise.json()["id"]),
    )


async def ensure_rubric(
    factory: async_sessionmaker[AsyncSession], active: bool = True
) -> uuid.UUID:
    """The shared test database holds one rubric row; create it on first use."""
    async with factory() as session:
        found = await session.scalar(
            select(RubricVersions.id).where(RubricVersions.version == RUBRIC_VERSION)
        )
        if found is not None:
            return found
        row = RubricVersions(
            version=RUBRIC_VERSION, dimensions={}, prompt_hash="test", is_active=active
        )
        session.add(row)
        await session.commit()
        return row.id


def dimensions(score: int = 4, **overrides: int) -> dict[str, Any]:
    """Judge-shaped ``evaluations.dimensions`` with every rubric key."""
    return {
        k: {"score": overrides.get(k, score), "evidence_turns": [], "reason": "r"}
        for k in DIMENSION_KEYS
    }


@dataclass
class Made:
    call_id: uuid.UUID
    run_id: uuid.UUID
    run_item_id: uuid.UUID
    evaluation_id: uuid.UUID | None


async def make_regression_test(
    factory: async_sessionmaker[AsyncSession],
    world: World,
    *,
    status: str = "blocking",
    baseline: float = 80,
    tolerance: float = 5,
    failure_type: str = "wrong_fact",
) -> uuid.UUID:
    async with factory() as session:
        row = RegressionTests(
            project_id=world.tenant.project_id,
            agent_id=world.agent_id,
            scenario_id=world.scenario_id,
            persona_id=world.persona_id,
            noise_profile_id=world.noise_id,
            failure_type=failure_type,
            status=status,
            baseline_score=baseline,
            tolerance=tolerance,
        )
        session.add(row)
        await session.commit()
        return row.id


async def make_run(
    factory: async_sessionmaker[AsyncSession], world: World, kind: str = "regression"
) -> uuid.UUID:
    async with factory() as session:
        run = TestRuns(
            project_id=world.tenant.project_id, agent_id=world.agent_id, kind=kind, status="running"
        )
        session.add(run)
        await session.commit()
        return run.id


async def make_call(
    factory: async_sessionmaker[AsyncSession],
    world: World,
    *,
    run_id: uuid.UUID | None = None,
    regression_test_id: uuid.UUID | None = None,
    score: float | None = 90,
    critical: bool = False,
    passed: bool | None = None,
    item_status: str = "evaluated",
    call_status: str = "completed",
    judge_dims: dict[str, Any] | None = None,
    summary: str = "Agent quoted the wrong EMI amount.",
    rubric_active: bool = True,
) -> Made:
    """A simulated call inside a run, with its evaluation when ``score`` is given."""
    rubric = await ensure_rubric(factory, rubric_active)
    async with factory() as session:
        if run_id is None:
            run = TestRuns(
                project_id=world.tenant.project_id,
                agent_id=world.agent_id,
                kind="regression" if regression_test_id else "matrix",
                status="running",
            )
            session.add(run)
            await session.flush()
            run_id = run.id
        item = RunItems(
            run_id=run_id,
            scenario_id=world.scenario_id,
            persona_id=world.persona_id,
            noise_profile_id=world.noise_id,
            seed=uuid.uuid4().int % 2**31,
            status=item_status,
            regression_test_id=regression_test_id,
        )
        session.add(item)
        await session.flush()
        call = Calls(
            project_id=world.tenant.project_id,
            source="simulation",
            status=call_status,
            agent_id=world.agent_id,
            run_item_id=item.id,
            end_reason="goal_achieved",
            language="kn-IN",
        )
        session.add(call)
        await session.flush()
        for idx, speaker, text in ((0, "agent", "Hello, EMI reminder."), (1, "caller", "I paid.")):
            session.add(
                Turns(
                    call_id=call.id,
                    idx=idx,
                    speaker=speaker,
                    text_=text,
                    text_masked=text,
                    start_ms=idx * 1000,
                    end_ms=idx * 1000 + 900,
                )
            )
        evaluation_id = None
        if score is not None:
            evaluation = Evaluations(
                call_id=call.id,
                rubric_version_id=rubric,
                judge_model="deepseek-test",
                prompt_hash="h",
                dimensions=judge_dims or dimensions(),
                critical_failure=critical,
                summary=summary,
                overall_score=score,
                passed=score >= 80 and not critical if passed is None else passed,
            )
            session.add(evaluation)
            await session.flush()
            evaluation_id = evaluation.id
        await session.commit()
        return Made(call.id, run_id, item.id, evaluation_id)


async def outbox_for(
    factory: async_sessionmaker[AsyncSession], payload_key: str, value: str
) -> list[AnyEnvelope]:
    """Outbox envelopes whose payload has ``payload_key == value``, oldest first."""
    async with factory() as session:
        rows = (await session.scalars(select(OutboxEvents).order_by(OutboxEvents.created_at))).all()
    found: list[AnyEnvelope] = []
    for row in rows:
        envelope = cast(dict[str, Any], row.envelope)
        if envelope["payload"].get(payload_key) == value:
            found.append(parse_envelope(envelope))
    return found
