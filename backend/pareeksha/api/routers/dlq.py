"""Dead letters (docs/06-api-spec.md section 9)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from pareeksha.api.auth import AdminKey, ReadKey
from pareeksha.api.deps import AUTH_ERRORS, Db, Pagination, errors
from pareeksha.ops import dlq
from pareeksha.schemas.common import Page
from pareeksha.schemas.system import DeadLetterOut, DeadLetterStatus

router = APIRouter(tags=["dlq"], responses=AUTH_ERRORS)


@router.get("/dlq", summary="List dead letters")
async def list_dead_letters(
    key: ReadKey, session: Db, page: Pagination, status: DeadLetterStatus = "open"
) -> Page[DeadLetterOut]:
    return await dlq.list_dead_letters(session, page, status)


@router.post(
    "/dlq/{dead_letter_id}/replay",
    status_code=202,
    responses=errors(404, 409),
    summary="Re-publish the envelope (attempt=1) to its original topic via the outbox",
)
async def replay_dead_letter(dead_letter_id: UUID, key: AdminKey, session: Db) -> DeadLetterOut:
    return await dlq.replay(session, dead_letter_id)


@router.post(
    "/dlq/{dead_letter_id}/discard",
    responses=errors(404, 409),
    summary="Mark a dead letter discarded",
)
async def discard_dead_letter(dead_letter_id: UUID, key: AdminKey, session: Db) -> DeadLetterOut:
    return await dlq.discard(session, dead_letter_id)
