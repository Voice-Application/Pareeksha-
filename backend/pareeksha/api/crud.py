"""Helpers shared by the CRUD routers: pagination, project-scoped lookups, constraint errors."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.deps import PageParams
from pareeksha.api.errors import ApiError

_UNIQUE_VIOLATION = "23505"
_FOREIGN_KEY_VIOLATION = "23503"
_CHECK_VIOLATION = "23514"


def encode_cursor(created_at: datetime, row_id: UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "i": str(row_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        return datetime.fromisoformat(data["t"]), UUID(data["i"])
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise ApiError(400, "validation_error", "Invalid cursor", {"cursor": cursor}) from exc


async def paginate(
    session: AsyncSession, model: Any, conditions: list[Any], page: PageParams
) -> tuple[list[Any], str | None]:
    """Newest first (``created_at DESC, id DESC``); returns the rows and the next cursor."""
    stmt = select(model).where(*conditions)
    if page.cursor:
        created_at, row_id = decode_cursor(page.cursor)
        stmt = stmt.where(tuple_(model.created_at, model.id) < tuple_(created_at, row_id))
    stmt = stmt.order_by(model.created_at.desc(), model.id.desc()).limit(page.limit + 1)
    rows = list((await session.scalars(stmt)).all())
    if len(rows) <= page.limit:
        return rows, None
    rows = rows[: page.limit]
    return rows, encode_cursor(rows[-1].created_at, rows[-1].id)


async def get_or_404(
    session: AsyncSession, model: Any, row_id: UUID, project_id: UUID, what: str
) -> Any:
    """The row with this id in the caller's project, else 404 ``not_found``."""
    stmt = select(model).where(model.id == row_id, model.project_id == project_id)
    row = (await session.scalars(stmt)).one_or_none()
    if row is None:
        raise ApiError(404, "not_found", f"{what} not found", {"id": str(row_id)})
    return row


def constraint_error(exc: IntegrityError, conflict_message: str) -> ApiError:
    """Map a Postgres constraint failure to the API error envelope (re-raise anything else)."""
    state = getattr(exc.orig, "sqlstate", None)
    if state in (_UNIQUE_VIOLATION, _FOREIGN_KEY_VIOLATION):
        return ApiError(409, "conflict", conflict_message)
    if state == _CHECK_VIOLATION:
        return ApiError(400, "validation_error", "Request violates a database constraint")
    raise exc


async def delete_row(session: AsyncSession, model: Any, row_id: UUID, in_use_message: str) -> None:
    """DELETE by id. A row that something still references is refused with 409 ``conflict``.

    A Core statement, not ``session.delete``: the ORM would try to null the referencing rows'
    foreign keys instead of letting Postgres refuse.
    """
    try:
        await session.execute(delete(model).where(model.id == row_id))
    except IntegrityError as exc:
        raise constraint_error(exc, in_use_message) from exc


async def flush(session: AsyncSession, conflict_message: str, refresh: Any = None) -> None:
    """Flush pending changes; unique/foreign-key violations become 409 ``conflict``."""
    try:
        await session.flush()
        if refresh is not None:
            await session.refresh(refresh)
    except IntegrityError as exc:
        raise constraint_error(exc, conflict_message) from exc
