"""Test designer chat and commit (docs/06-api-spec.md section 14)."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.auth import WriteKey
from pareeksha.api.deps import AUTH_ERRORS, Db, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.llm_deps import LlmBuilder, usage_sink
from pareeksha.api.ratelimit import DESIGNER_CHAT_LIMIT
from pareeksha.api.routers.agents import create_agent
from pareeksha.api.routers.personas import create_persona
from pareeksha.api.routers.scenarios import create_scenario
from pareeksha.db.models import NoiseProfiles, Personas
from pareeksha.db.session import SessionFactory, get_session_factory
from pareeksha.designer.service import chat_turn
from pareeksha.llm._http import public_error
from pareeksha.llm.base import LLMError
from pareeksha.llm.client import JSONGenerationError
from pareeksha.llm.config import LLMConfigError
from pareeksha.llm.project_settings import effective_llm_settings
from pareeksha.regression.estimate import remaining_budget
from pareeksha.schemas.agents import AgentCreate
from pareeksha.schemas.designer import (
    DesignerChatRequest,
    DesignerChatResponse,
    DesignerCommitRequest,
    DesignerCommitResult,
    ExistingPersona,
)
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

router = APIRouter(tags=["designer"], responses=AUTH_ERRORS)

LIBRARY_LIMIT = 100


@router.post(
    "/designer/chat",
    responses=errors(402, 422, 429, 502),
    summary="One turn with the test designer assistant (stateless: send the whole history)",
)
async def designer_chat(
    body: DesignerChatRequest,
    key: WriteKey,
    session: Db,
    build: LlmBuilder,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> DesignerChatResponse:
    DESIGNER_CHAT_LIMIT.check(key.key_id)
    remaining = await remaining_budget(session, key.project_id)
    if remaining is not None and remaining <= 0:
        raise ApiError(
            402,
            "budget_exceeded",
            "The project's budget is used up",
            {"remaining_budget": remaining},
        )
    personas = [
        {
            "id": str(r.id),
            "name": r.name,
            "language": r.language,
            "dialect": r.dialect_label,
            "code_mix": r.code_mix_style,
            "emotion": r.emotion,
            "notes": (r.behaviour_notes or "")[:120],
        }
        for r in await session.scalars(
            select(Personas)
            .where(Personas.project_id == key.project_id)
            .order_by(Personas.name)
            .limit(LIBRARY_LIMIT)
        )
    ]
    noise = [
        {
            "id": str(r.id),
            "name": r.name,
            "description": (r.description or "")[:160],
            "codec": r.codec,
            "background": r.background_category,
            "snr_db": r.snr_db,
        }
        for r in await session.scalars(
            select(NoiseProfiles)
            .where(NoiseProfiles.project_id == key.project_id)
            .order_by(NoiseProfiles.name)
            .limit(LIBRARY_LIMIT)
        )
    ]
    try:
        settings = await effective_llm_settings(session, key.project_id)
        client = build(settings, usage_sink(factory, key.project_id))
    except LLMConfigError as exc:
        raise ApiError(422, "llm_not_configured", str(exc)) from exc
    secret = settings.deepseek_api_key or settings.gemini_api_key
    try:
        return await chat_turn(client, body, personas, noise)
    except JSONGenerationError as exc:
        raise ApiError(
            502,
            "designer_invalid_output",
            "The model did not return a usable draft, even after a retry; try again or "
            "simplify the request.",
        ) from exc
    except LLMConfigError as exc:
        raise ApiError(422, "llm_not_configured", str(exc)) from exc
    except LLMError as exc:
        raise ApiError(502, "upstream_error", public_error(exc, secret)) from exc
    finally:
        await client.aclose()


async def _require_ids(
    session: AsyncSession, model: Any, ids: list[UUID], project_id: UUID, label: str
) -> None:
    if not ids:
        return
    found = set(
        await session.scalars(
            select(model.id).where(model.id.in_(ids), model.project_id == project_id)
        )
    )
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise ApiError(404, "not_found", f"{label} not found in this project", {"ids": missing})


@router.post(
    "/designer/commit",
    status_code=201,
    responses=errors(404, 409, 422),
    summary="Create the agent, scenarios and new personas of a draft in one transaction",
)
async def designer_commit(
    body: DesignerCommitRequest, key: WriteKey, session: Db
) -> DesignerCommitResult:
    draft = body.draft
    if not draft.agent.endpoint_url:
        raise ApiError(
            422,
            "validation_error",
            "draft.agent.endpoint_url is required to commit",
            {"field": "draft.agent.endpoint_url"},
        )
    existing_personas = list(
        dict.fromkeys(p.existing_id for p in draft.personas if isinstance(p, ExistingPersona))
    )
    noise_ids = list(dict.fromkeys(draft.noise_profile_ids))
    await _require_ids(session, Personas, existing_personas, key.project_id, "Persona")
    await _require_ids(session, NoiseProfiles, noise_ids, key.project_id, "Noise profile")

    # The agent / scenario / persona routes' own create functions: same defaults, same 409s,
    # all in this request's transaction (any error rolls everything back).
    agent = await create_agent(AgentCreate(**draft.agent.model_dump(mode="json")), key, session)
    scenario_ids = [
        (
            await create_scenario(
                ScenarioCreate(**{**s.model_dump(), "agent_id": agent.id}), key, session
            )
        ).id
        for s in draft.scenarios
    ]
    persona_ids: list[UUID] = []
    for entry in draft.personas:
        if isinstance(entry, ExistingPersona):
            persona_ids.append(entry.existing_id)
        else:
            created = await create_persona(PersonaCreate(**entry.new.model_dump()), key, session)
            persona_ids.append(created.id)
    persona_ids = list(dict.fromkeys(persona_ids))
    path = (
        f"/runs/new?agent={agent.id}&s={','.join(map(str, scenario_ids))}"
        f"&p={','.join(map(str, persona_ids))}&l={','.join(map(str, noise_ids))}&step=review"
    )
    return DesignerCommitResult(
        agent_id=agent.id,
        scenario_ids=scenario_ids,
        persona_ids=persona_ids,
        noise_profile_ids=noise_ids,
        calls=len(scenario_ids) * len(persona_ids) * len(noise_ids),
        run_wizard_path=path,
    )
