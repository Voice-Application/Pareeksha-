"""Transactional outbox (TRD section 10.4).

``enqueue`` is called by the API inside the same DB transaction that writes the domain rows, so a
run can never exist without its event or vice versa. ``relay_once`` is the relay's unit of work:
claim unpublished rows (``FOR UPDATE SKIP LOCKED``), publish with ``acks=all``, stamp
``published_at``. A crash between publish and stamp re-publishes the row (at-least-once); consumers
deduplicate on ``event_id``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from pareeksha.events.producer import EventProducer
from pareeksha.events.schemas import AnyEnvelope

log = logging.getLogger(__name__)

BATCH_SIZE = 100
#: Published rows are pruned after 3 days (docs/04-system-design.md data lifecycle).
PRUNE_AFTER = timedelta(days=3)


async def enqueue(conn: psycopg.AsyncConnection[Any], envelope: AnyEnvelope) -> None:
    """Insert ``envelope`` into ``outbox_events`` using the caller's open transaction.

    ``outbox_events.id`` is the envelope ``event_id``, so enqueueing the same event twice is a
    primary-key violation rather than a duplicate message.
    """
    await conn.execute(
        "INSERT INTO outbox_events (id, topic, key, envelope, created_at) "
        "VALUES (%s, %s, %s, %s, clock_timestamp())",  # clock: keeps insert order within a tx
        (
            envelope.event_id,
            envelope.topic.value,
            envelope.partition_key(),
            Jsonb(envelope.model_dump(mode="json")),
        ),
    )


@dataclass(frozen=True, slots=True)
class RelayResult:
    published: int
    failed: int  # 0 or 1: a batch stops at the first publish failure (broker unavailable)
    last_error: str | None = None


async def relay_once(
    conn: psycopg.AsyncConnection[Any], producer: EventProducer, *, batch_size: int = BATCH_SIZE
) -> RelayResult:
    """Publish up to ``batch_size`` unpublished rows, oldest first.

    On a publish failure the row's ``attempts`` / ``last_error`` are recorded, the rows already
    published in this batch stay published, and the batch stops (the broker is likely down).
    """
    published = 0
    failed = 0
    last_error: str | None = None
    async with conn.transaction():
        cur = await conn.execute(
            "SELECT id, topic, key, envelope FROM outbox_events WHERE published_at IS NULL "
            "ORDER BY created_at, id LIMIT %s FOR UPDATE SKIP LOCKED",
            (batch_size,),
        )
        for row_id, topic, key, envelope in await cur.fetchall():
            try:
                await producer.send(
                    topic, json.dumps(envelope).encode("utf-8"), key=key.encode("utf-8")
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:1000]
                await conn.execute(
                    "UPDATE outbox_events SET attempts = attempts + 1, last_error = %s "
                    "WHERE id = %s",
                    (last_error, row_id),
                )
                failed = 1
                log.warning("outbox publish failed", extra={"event_id": str(row_id)}, exc_info=True)
                break
            await conn.execute(
                "UPDATE outbox_events SET published_at = now(), attempts = attempts + 1, "
                "last_error = NULL WHERE id = %s",
                (row_id,),
            )
            published += 1
    return RelayResult(published, failed, last_error)


async def prune_published(
    conn: psycopg.AsyncConnection[Any], older_than: timedelta = PRUNE_AFTER
) -> int:
    """Delete published rows older than ``older_than``; returns how many."""
    cur = await conn.execute(
        "DELETE FROM outbox_events WHERE published_at IS NOT NULL AND published_at < now() - %s",
        (older_than,),
    )
    return cur.rowcount


async def backlog(conn: psycopg.AsyncConnection[Any]) -> int:
    """Number of unpublished rows (surfaced by ``/metrics/summary``)."""
    cur = await conn.execute("SELECT count(*) FROM outbox_events WHERE published_at IS NULL")
    row = await cur.fetchone()
    return int(row[0]) if row else 0
