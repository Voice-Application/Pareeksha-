"""The one place that decides which knowledge-base documents are live (soft delete)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.db.models import KbDocuments


async def active_document_ids(session: AsyncSession, kb_id: UUID) -> list[UUID]:
    """Non-deleted document ids of a KB, oldest first; the index build snapshots these.

    Raw SQL equivalent: ``... FROM kb_documents WHERE kb_id = %s AND deleted_at IS NULL``.
    """
    stmt = (
        select(KbDocuments.id)
        .where(KbDocuments.kb_id == kb_id, KbDocuments.deleted_at.is_(None))
        .order_by(KbDocuments.created_at, KbDocuments.id)
    )
    return list((await session.scalars(stmt)).all())
