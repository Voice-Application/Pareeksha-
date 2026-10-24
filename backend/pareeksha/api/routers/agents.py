"""Agents (docs/06-api-spec.md section 1)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.agents import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    TestConnectionResult,
)
from pareeksha.schemas.common import Page

router = APIRouter(tags=["agents"], responses=AUTH_ERRORS)


@router.post(
    "/agents",
    status_code=201,
    dependencies=[scoped("runs:write")],
    responses=errors(409),
    summary="Register an agent under test",
)
async def create_agent(body: AgentCreate) -> AgentOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.get("/agents", dependencies=[scoped("read")], summary="List agents")
async def list_agents(page: Pagination, include_archived: bool = False) -> Page[AgentOut]:
    # STUB(API-02)
    not_implemented("API-02")


@router.get(
    "/agents/{agent_id}",
    dependencies=[scoped("read")],
    responses=errors(404),
    summary="Get an agent",
)
async def get_agent(agent_id: UUID) -> AgentOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.patch(
    "/agents/{agent_id}",
    dependencies=[scoped("runs:write")],
    responses=errors(404, 409),
    summary="Update an agent",
)
async def update_agent(agent_id: UUID, body: AgentUpdate) -> AgentOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.post(
    "/agents/{agent_id}/archive",
    dependencies=[scoped("runs:write")],
    responses=errors(404),
    summary="Archive an agent",
)
async def archive_agent(agent_id: UUID) -> AgentOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.post(
    "/agents/{agent_id}/test-connection",
    dependencies=[scoped("runs:write")],
    responses=errors(404),
    summary="Open the socket, send 1 s of silence, wait up to 10 s for agent audio",
)
async def test_agent_connection(agent_id: UUID) -> TestConnectionResult:
    # STUB(VOICE-04)
    not_implemented("VOICE-04")
