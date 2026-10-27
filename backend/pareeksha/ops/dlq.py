"""Dead letters: list, replay, discard (docs/06-api-spec.md section 9, FR-IN-10).

``dead_letters`` is written by the DLQ recorder. Replay puts the stored envelope back on its
original topic through the outbox with ``attempt = 1`` and the **same** ``event_id``: consumer
groups that already processed it skip it (``processed_events``), the group that failed handles it
again, and if it fails again the recorder re-opens the same row. The outbox row gets a fresh id
(its primary key) so replaying an event that is still in the outbox table cannot collide.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.crud import paginate_rows
from pareeksha.api.deps import PageParams
from pareeksha.api.errors import ApiError
from pareeksha.db.models import DeadLetters, OutboxEvents
from pareeksha.events.schemas import parse_envelope
from pareeksha.schemas.common import Page
from pareeksha.schemas.system import DeadLetterOut


def _out(row: DeadLetters) -> DeadLetterOut:
    return DeadLetterOut(
        id=row.id,
        event_id=row.event_id,
        original_topic=row.original_topic,
        consumer_group=row.consumer_group,
        error=row.error,
        attempts=row.attempts,
        status=cast("Any", row.status),
        failed_at=row.failed_at,
        envelope=cast("dict[str, Any]", row.envelope),
    )


async def list_dead_letters(
    session: AsyncSession, page: PageParams, status: str
) -> Page[DeadLetterOut]:
    stmt = select(DeadLetters).where(DeadLetters.status == status)
    rows, next_cursor = await paginate_rows(
        session,
        stmt,
        DeadLetters.failed_at,
        DeadLetters.id,
        page,
        key_of=lambda row: (row[0].failed_at, row[0].id),
    )
    return Page(items=[_out(r[0]) for r in rows], next_cursor=next_cursor)


async def _open_row(session: AsyncSession, dead_letter_id: uuid.UUID) -> DeadLetters:
    row = (
        await session.scalars(
            select(DeadLetters).where(DeadLetters.id == dead_letter_id).with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", "Dead letter not found", {"id": str(dead_letter_id)})
    if row.status != "open":
        raise ApiError(
            409, "conflict", f"Dead letter is already {row.status}", {"status": row.status}
        )
    return row


async def replay(session: AsyncSession, dead_letter_id: uuid.UUID) -> DeadLetterOut:
    row = await _open_row(session, dead_letter_id)
    envelope = {**cast("dict[str, Any]", row.envelope), "attempt": 1}
    try:
        parse_envelope(envelope)  # raw / unparseable messages cannot be put back on a topic
    except Exception as exc:
        raise ApiError(
            409,
            "conflict",
            "The stored message is not a valid event envelope and cannot be replayed",
            {"reason": str(exc)[:300]},
        ) from exc
    session.add(
        OutboxEvents(
            id=uuid.uuid4(),
            topic=row.original_topic,
            key=row.key,
            envelope=envelope,
            created_at=func.clock_timestamp(),
        )
    )
    row.status = "replayed"
    row.replayed_at = datetime.now(UTC)
    await session.flush()
    return _out(row)


async def discard(session: AsyncSession, dead_letter_id: uuid.UUID) -> DeadLetterOut:
    row = await _open_row(session, dead_letter_id)
    row.status = "discarded"
    await session.flush()
    return _out(row)
