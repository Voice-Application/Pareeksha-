"""Agents (docs/06-api-spec.md section 1)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter

from pareeksha.api.auth import ReadKey, WriteKey, scoped
from pareeksha.api.crud import flush, get_or_404, paginate
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.db.models import Agents
from pareeksha.schemas.agents import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    TestConnectionResult,
)
from pareeksha.schemas.common import Page

router = APIRouter(tags=["agents"], responses=AUTH_ERRORS)

_DUPLICATE = "An agent with this name already exists"


def _out(row: Agents) -> AgentOut:
    return AgentOut.model_validate(row, from_attributes=True)


@router.post(
    "/agents",
    status_code=201,
    responses=errors(409),
    summary="Register an agent under test",
)
async def create_agent(body: AgentCreate, key: WriteKey, session: Db) -> AgentOut:
    row = Agents(project_id=key.project_id, **body.model_dump(mode="json"))
    session.add(row)
    await flush(session, _DUPLICATE, refresh=row)
    return _out(row)


@router.get("/agents", summary="List agents")
async def list_agents(
    key: ReadKey, session: Db, page: Pagination, include_archived: bool = False
) -> Page[AgentOut]:
    conditions = [Agents.project_id == key.project_id]
    if not include_archived:
        conditions.append(Agents.archived.is_(False))
    rows, next_cursor = await paginate(session, Agents, conditions, page)
    return Page(items=[_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/agents/{agent_id}", responses=errors(404), summary="Get an agent")
async def get_agent(agent_id: UUID, key: ReadKey, session: Db) -> AgentOut:
    return _out(await get_or_404(session, Agents, agent_id, key.project_id, "Agent"))


@router.patch("/agents/{agent_id}", responses=errors(404, 409), summary="Update an agent")
async def update_agent(agent_id: UUID, body: AgentUpdate, key: WriteKey, session: Db) -> AgentOut:
    row = await get_or_404(session, Agents, agent_id, key.project_id, "Agent")
    for field, value in body.model_dump(mode="json", exclude_none=True).items():
        setattr(row, field, value)
    row.updated_at = datetime.now(UTC)
    await flush(session, _DUPLICATE)
    return _out(row)


@router.post("/agents/{agent_id}/archive", responses=errors(404), summary="Archive an agent")
async def archive_agent(agent_id: UUID, key: WriteKey, session: Db) -> AgentOut:
    row = await get_or_404(session, Agents, agent_id, key.project_id, "Agent")
    if not row.archived:
        row.archived = True
        row.updated_at = datetime.now(UTC)
        await flush(session, _DUPLICATE)
    return _out(row)


@router.post(
    "/agents/{agent_id}/test-connection",
    dependencies=[scoped("runs:write")],
    responses=errors(404),
    summary="Open the socket, send 1 s of silence, wait up to 10 s for agent audio",
)
async def test_agent_connection(agent_id: UUID) -> TestConnectionResult:
    # STUB(VOICE-04)
    not_implemented("VOICE-04")
