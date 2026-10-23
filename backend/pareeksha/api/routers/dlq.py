"""Dead letters (docs/06-api-spec.md section 9)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from pareeksha.api.auth import scoped
from pareeksha.api.deps import AUTH_ERRORS, Pagination, errors
from pareeksha.api.stubs import not_implemented
from pareeksha.schemas.common import Page
from pareeksha.schemas.system import DeadLetterOut, DeadLetterStatus

router = APIRouter(tags=["dlq"], responses=AUTH_ERRORS)


@router.get("/dlq", dependencies=[scoped("read")], summary="List dead letters")
async def list_dead_letters(
    page: Pagination, status: DeadLetterStatus = "open"
) -> Page[DeadLetterOut]:
    # STUB(API-04)
    not_implemented("API-04")


@router.post(
    "/dlq/{dead_letter_id}/replay",
    status_code=202,
    dependencies=[scoped("admin")],
    responses=errors(404, 409),
    summary="Re-publish the envelope (attempt=1) to its original topic via the outbox",
)
async def replay_dead_letter(dead_letter_id: UUID) -> DeadLetterOut:
    # STUB(API-04)
    not_implemented("API-04")


@router.post(
    "/dlq/{dead_letter_id}/discard",
    dependencies=[scoped("admin")],
    responses=errors(404, 409),
    summary="Mark a dead letter discarded",
)
async def discard_dead_letter(dead_letter_id: UUID) -> DeadLetterOut:
    # STUB(API-04)
    not_implemented("API-04")
