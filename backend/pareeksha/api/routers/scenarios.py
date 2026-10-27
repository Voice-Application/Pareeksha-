"""Scenarios and scenario drafts (docs/06-api-spec.md section 2)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.auth import ReadKey, WriteKey
from pareeksha.api.crud import delete_row, flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, errors
from pareeksha.api.errors import ApiError
from pareeksha.api.outbox import enqueue_event
from pareeksha.db.models import Agents, ScenarioDrafts, Scenarios
from pareeksha.events.schemas import ScenarioGenerateRequested, make_envelope
from pareeksha.scenario_gen.generator import CATEGORIES
from pareeksha.schemas.common import Page
from pareeksha.schemas.scenarios import (
    DraftAccepted,
    ScenarioBulkCreate,
    ScenarioBulkResult,
    ScenarioCreate,
    ScenarioDraftOut,
    ScenarioGenerateRequest,
    ScenarioOut,
    ScenarioUpdate,
)

router = APIRouter(tags=["scenarios"], responses=AUTH_ERRORS)

_IN_USE = "Scenario is referenced by a run and cannot be deleted"


def _out(row: Scenarios) -> ScenarioOut:
    return ScenarioOut.model_validate(row, from_attributes=True)


async def _require_agent(session: AsyncSession, agent_id: UUID | None, project_id: UUID) -> None:
    """A scenario may only point at an agent of the caller's project (400 otherwise)."""
    if agent_id is None:
        return
    found = await session.scalar(
        select(Agents.id).where(Agents.id == agent_id, Agents.project_id == project_id)
    )
    if found is None:
        raise ApiError(
            400, "validation_error", "agent_id does not exist", {"agent_id": str(agent_id)}
        )


@router.post("/scenarios", status_code=201)
async def create_scenario(body: ScenarioCreate, key: WriteKey, session: Db) -> ScenarioOut:
    await _require_agent(session, body.agent_id, key.project_id)
    row = Scenarios(project_id=key.project_id, source="manual", **body.model_dump())
    session.add(row)
    await flush(session, "Scenario could not be saved", refresh=row)
    return _out(row)


@router.post(
    "/scenarios:bulk",
    status_code=201,
    summary="Save reviewed scenario drafts in one call",
)
async def bulk_create_scenarios(
    body: ScenarioBulkCreate, key: WriteKey, session: Db
) -> ScenarioBulkResult:
    for agent_id in {s.agent_id for s in body.scenarios}:
        await _require_agent(session, agent_id, key.project_id)
    rows = [
        Scenarios(project_id=key.project_id, source=body.source, **s.model_dump())
        for s in body.scenarios
    ]
    session.add_all(rows)
    await flush(session, "Scenarios could not be saved")
    for row in rows:
        await session.refresh(row)
    return ScenarioBulkResult(items=[_out(r) for r in rows])


@router.get("/scenarios")
async def list_scenarios(
    key: ReadKey,
    session: Db,
    page: Pagination,
    agent_id: UUID | None = None,
    tag: str | None = None,
) -> Page[ScenarioOut]:
    conditions = [Scenarios.project_id == key.project_id]
    if agent_id is not None:
        conditions.append(Scenarios.agent_id == agent_id)
    if tag is not None:
        conditions.append(Scenarios.tags.contains([tag]))
    rows, next_cursor = await paginate(session, Scenarios, conditions, page)
    return Page(items=[_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/scenarios/{scenario_id}", responses=errors(404))
async def get_scenario(scenario_id: UUID, key: ReadKey, session: Db) -> ScenarioOut:
    return _out(await get_or_404(session, Scenarios, scenario_id, key.project_id, "Scenario"))


@router.patch("/scenarios/{scenario_id}", responses=errors(404))
async def update_scenario(
    scenario_id: UUID, body: ScenarioUpdate, key: WriteKey, session: Db
) -> ScenarioOut:
    row = await get_or_404(session, Scenarios, scenario_id, key.project_id, "Scenario")
    changes = body.model_dump(exclude_unset=True)
    # agent_id may be set to null (reusable across agents); every other column is NOT NULL.
    changes = {k: v for k, v in changes.items() if v is not None or k == "agent_id"}
    if changes.get("agent_id") is not None:
        await _require_agent(session, changes["agent_id"], key.project_id)
    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_at = datetime.now(UTC)
    await flush(session, "Scenario could not be saved")
    return _out(row)


@router.delete(
    "/scenarios/{scenario_id}",
    status_code=204,
    responses=errors(404, 409),
    summary="Delete a scenario (409 if referenced by a run)",
)
async def delete_scenario(scenario_id: UUID, key: WriteKey, session: Db) -> Response:
    row = await get_or_404(session, Scenarios, scenario_id, key.project_id, "Scenario")
    await delete_row(session, Scenarios, row.id, _IN_USE)
    return Response(status_code=204)


@router.post(
    "/agents/{agent_id}/scenarios:generate",
    status_code=202,
    responses=errors(404),
    summary="Generate scenario drafts with the LLM (drafts are not saved)",
)
async def generate_scenarios(
    agent_id: UUID, body: ScenarioGenerateRequest, key: WriteKey, session: Db
) -> DraftAccepted:
    agent = await get_or_404(session, Agents, agent_id, key.project_id, "Agent")
    unknown = sorted(set(body.mix) - set(CATEGORIES))
    if unknown or any(n < 0 for n in body.mix.values()):
        raise ApiError(
            400,
            "validation_error",
            f"mix keys must be among {list(CATEGORIES)} with counts >= 0",
            {"mix": body.mix},
        )
    if body.mix and sum(body.mix.values()) != body.count:
        raise ApiError(
            400,
            "validation_error",
            "mix must add up to count",
            {"count": body.count, "mix_total": sum(body.mix.values())},
        )
    draft = ScenarioDrafts(agent_id=agent.id, status="pending", request=body.model_dump())
    session.add(draft)
    await flush(session, "Draft could not be created")
    enqueue_event(
        session,
        make_envelope(
            ScenarioGenerateRequested(
                draft_id=draft.id, agent_id=agent.id, count=body.count, mix=body.mix
            ),
            producer="api",
            correlation_id=str(draft.id),
        ),
    )
    return DraftAccepted(draft_id=draft.id)


@router.get(
    "/scenario-drafts/{draft_id}",
    responses=errors(404),
    summary="Poll a draft until status is ready",
)
async def get_scenario_draft(draft_id: UUID, key: ReadKey, session: Db) -> ScenarioDraftOut:
    stmt = (
        select(ScenarioDrafts)
        .join(Agents, Agents.id == ScenarioDrafts.agent_id)
        .where(ScenarioDrafts.id == draft_id, Agents.project_id == key.project_id)
    )
    row = (await session.scalars(stmt)).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "Draft not found", {"id": str(draft_id)})
    return ScenarioDraftOut.model_validate(
        {
            "id": row.id,
            "agent_id": row.agent_id,
            "status": row.status,
            "request": row.request,
            "drafts": row.drafts,
            "error": row.error,
            "created_at": row.created_at,
        }
    )
