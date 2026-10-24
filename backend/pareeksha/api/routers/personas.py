"""Personas (docs/06-api-spec.md section 2)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, binary_response, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.common import Page
from pareeksha.schemas.personas import PersonaCreate, PersonaOut, PersonaUpdate

router = APIRouter(tags=["personas"], responses=AUTH_ERRORS)


@router.post(
    "/personas", status_code=201, dependencies=[scoped("runs:write")], responses=errors(409)
)
async def create_persona(body: PersonaCreate) -> PersonaOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.get("/personas", dependencies=[scoped("read")])
async def list_personas(page: Pagination, language: str | None = None) -> Page[PersonaOut]:
    # STUB(API-02)
    not_implemented("API-02")


@router.get("/personas/{persona_id}", dependencies=[scoped("read")], responses=errors(404))
async def get_persona(persona_id: UUID) -> PersonaOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.patch(
    "/personas/{persona_id}", dependencies=[scoped("runs:write")], responses=errors(404, 409)
)
async def update_persona(persona_id: UUID, body: PersonaUpdate) -> PersonaOut:
    # STUB(API-02)
    not_implemented("API-02")


@router.delete(
    "/personas/{persona_id}",
    status_code=204,
    dependencies=[scoped("runs:write")],
    responses=errors(404, 409),
    summary="Delete a persona (409 if referenced by a run)",
)
async def delete_persona(persona_id: UUID) -> Response:
    # STUB(API-02)
    not_implemented("API-02")


@router.post(
    "/personas/{persona_id}/preview",
    dependencies=[scoped("read")],
    response_class=Response,
    responses={
        **binary_response("audio/wav", "One sample line in the persona's voice"),
        **errors(404, 502),
    },
    summary="Synthesise one sample line (audio/wav)",
)
async def preview_persona(persona_id: UUID) -> Response:
    # STUB(API-02)
    not_implemented("API-02")
