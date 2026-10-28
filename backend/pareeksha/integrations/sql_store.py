"""``DeliveryStore`` over the ``integration_deliveries`` table (docs/schema.sql).

The unique key ``(integration_id, event_id, direction)`` is the idempotency guard: ``claim`` is a
single ``INSERT ... ON CONFLICT DO NOTHING`` so two workers racing on one event cannot both own the
row. The store must be given an **autocommit** connection that is separate from the consumer's
transaction: every claim and result is durable at once, so a consumer retry (transaction rolled
back) or a crash after the HTTP call still finds the row and never starts a second delivery.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pareeksha.integrations.delivery import DeliveryRecord, Direction

_COLUMNS = (
    "id, integration_id, event_id, direction, status, attempts, http_status, external_id, "
    "request_summary, response_excerpt, created_at, updated_at"
)
_INSERT = (
    "INSERT INTO integration_deliveries (integration_id, event_id, direction) "
    "VALUES (%s, %s, %s) ON CONFLICT (integration_id, event_id, direction) DO NOTHING "
    "RETURNING " + _COLUMNS
)
_SELECT_KEY = (
    "SELECT " + _COLUMNS + " FROM integration_deliveries "
    "WHERE integration_id = %s AND event_id = %s AND direction = %s"
)
_SELECT_ID = "SELECT " + _COLUMNS + " FROM integration_deliveries WHERE id = %s"
_SELECT_RECENT = (
    "SELECT " + _COLUMNS + " FROM integration_deliveries WHERE integration_id = %s "
    "ORDER BY created_at DESC, id DESC LIMIT %s"
)
_UPDATE = (
    "UPDATE integration_deliveries SET status = %s, attempts = %s, http_status = %s, "
    "external_id = %s, request_summary = %s, response_excerpt = %s, updated_at = now() "
    "WHERE id = %s"
)


def _record(row: dict[str, Any]) -> DeliveryRecord:
    return DeliveryRecord(
        id=row["id"],
        integration_id=row["integration_id"],
        event_id=row["event_id"],
        direction=row["direction"],
        status=row["status"],
        attempts=row["attempts"],
        http_status=row["http_status"],
        external_id=row["external_id"],
        request_summary=row["request_summary"] or {},
        response_excerpt=row["response_excerpt"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PsycopgDeliveryStore:
    def __init__(self, conn: psycopg.AsyncConnection[Any]) -> None:
        if not conn.autocommit:
            raise ValueError("PsycopgDeliveryStore needs an autocommit connection")
        self._conn = conn

    async def _one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchone()

    async def claim(
        self, integration_id: uuid.UUID, event_id: uuid.UUID, direction: Direction
    ) -> tuple[DeliveryRecord, bool]:
        created = await self._one(_INSERT, (integration_id, event_id, direction))
        if created is not None:
            return _record(created), True
        existing = await self._one(_SELECT_KEY, (integration_id, event_id, direction))
        if existing is None:  # the integration was deleted between the two statements
            raise LookupError(f"integration {integration_id} no longer exists")
        return _record(existing), False

    async def save(self, record: DeliveryRecord) -> None:
        await self._conn.execute(
            _UPDATE,
            (
                record.status,
                record.attempts,
                record.http_status,
                record.external_id,
                Jsonb(record.request_summary),
                record.response_excerpt,
                record.id,
            ),
        )

    async def get(self, delivery_id: uuid.UUID) -> DeliveryRecord | None:
        row = await self._one(_SELECT_ID, (delivery_id,))
        return None if row is None else _record(row)

    async def recent(self, integration_id: uuid.UUID, limit: int = 100) -> list[DeliveryRecord]:
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_SELECT_RECENT, (integration_id, limit))
            return [_record(r) for r in await cur.fetchall()]
