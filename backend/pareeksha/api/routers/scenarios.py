"""Scenarios and scenario drafts (docs/06-api-spec.md section 2)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, errors
from pareeksha.api.stubs import not_implemented
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


@router.post("/scenarios", status_code=201, dependencies=[scoped("runs:write")])
async def create_scenario(body: ScenarioCreate) -> ScenarioOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.post(
    "/scenarios:bulk",
    status_code=201,
    dependencies=[scoped("runs:write")],
    summary="Save reviewed scenario drafts in one call",
)
async def bulk_create_scenarios(body: ScenarioBulkCreate) -> ScenarioBulkResult:
    # STUB(API-02)
    not_implemented("API-02")


@router.get("/scenarios", dependencies=[scoped("read")])
async def list_scenarios(
    page: Pagination, agent_id: UUID | None = None, tag: str | None = None
) -> Page[ScenarioOut]:
    # STUB(API-02)
    not_implemented("API-02")


@router.get("/scenarios/{scenario_id}", dependencies=[scoped("read")], responses=errors(404))
async def get_scenario(scenario_id: UUID) -> ScenarioOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.patch(
    "/scenarios/{scenario_id}", dependencies=[scoped("runs:write")], responses=errors(404)
)
async def update_scenario(scenario_id: UUID, body: ScenarioUpdate) -> ScenarioOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.delete(
    "/scenarios/{scenario_id}",
    status_code=204,
    dependencies=[scoped("runs:write")],
    responses=errors(404, 409),
    summary="Delete a scenario (409 if referenced by a run)",
)
async def delete_scenario(scenario_id: UUID) -> Response:
    # STUB(API-02)
    not_implemented("API-02")


@router.post(
    "/agents/{agent_id}/scenarios:generate",
    status_code=202,
    dependencies=[scoped("runs:write")],
    responses=errors(404),
    summary="Generate scenario drafts with the LLM (drafts are not saved)",
)
async def generate_scenarios(agent_id: UUID, body: ScenarioGenerateRequest) -> DraftAccepted:
    # STUB(API-05)
    not_implemented("API-05")


@router.get(
    "/scenario-drafts/{draft_id}",
    dependencies=[scoped("read")],
    responses=errors(404),
    summary="Poll a draft until status is ready",
)
async def get_scenario_draft(draft_id: UUID) -> ScenarioDraftOut:
    # STUB(API-05)
    not_implemented("API-05")
