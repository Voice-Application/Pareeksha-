"""``GET /metrics/summary`` and ``GET /usage`` (docs/06-api-spec.md section 6, NFR-16).

Consumer lag is read from Kafka: for every consumer group, the sum over its committed partitions
of ``log end offset - committed offset``. A partition of a topic the group has committed on but
not on this partition counts from the log start. Outbox backlog, open DLQ count and credits used
come from Postgres.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import Any, cast

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pareeksha.api.errors import ApiError
from pareeksha.db.models import ApiUsage, DeadLetters, OutboxEvents
from pareeksha.runs.estimate import budget_credits, remaining_budget
from pareeksha.schemas.system import MetricsSummary, UsageOut, UsageRow

KAFKA_TIMEOUT_S = 10.0


async def _committed_offsets(bootstrap_servers: str) -> dict[str, dict[TopicPartition, int]]:
    """``{group: {partition: committed offset}}`` for every consumer group of the cluster."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers, client_id="pareeksha-metrics")
    await admin.start()
    try:
        groups = sorted(g[0] for g in await admin.list_consumer_groups())
        out: dict[str, dict[TopicPartition, int]] = {}
        for group in groups:
            offsets = await admin.list_consumer_group_offsets(group)
            out[group] = {tp: om.offset for tp, om in offsets.items() if om.offset >= 0}
        return out
    finally:
        with contextlib.suppress(Exception):
            await admin.close()


async def _consumer_lag(bootstrap_servers: str) -> dict[str, int]:
    committed = await _committed_offsets(bootstrap_servers)
    topics = sorted({tp.topic for offs in committed.values() for tp in offs})
    if not topics:
        return {}
    # A group-less consumer subscribed to the topics is assigned every partition of them.
    reader = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap_servers,
        group_id=None,
        client_id="pareeksha-metrics-reader",
    )
    await reader.start()
    try:
        while not reader.assignment():
            await asyncio.sleep(0.05)
        partitions = sorted(reader.assignment(), key=lambda tp: (tp.topic, tp.partition))
        ends = await reader.end_offsets(partitions)
        begins = await reader.beginning_offsets(partitions)
    finally:
        with contextlib.suppress(Exception):
            await reader.stop()
    lag: dict[str, int] = {}
    for group, offs in committed.items():
        if not offs:
            continue
        group_topics = {tp.topic for tp in offs}
        lag[group] = sum(
            max(ends[tp] - offs.get(tp, begins[tp]), 0)
            for tp in partitions
            if tp.topic in group_topics
        )
    return lag


async def consumer_lag(bootstrap_servers: str) -> dict[str, int]:
    """Lag per consumer group; 502 ``upstream_error`` when Kafka cannot be reached."""
    try:
        return await asyncio.wait_for(_consumer_lag(bootstrap_servers), KAFKA_TIMEOUT_S)
    except Exception as exc:
        raise ApiError(
            502, "upstream_error", "Consumer lag is unavailable (Kafka unreachable)"
        ) from exc


async def _credits_used(session: AsyncSession) -> float:
    return float(await session.scalar(select(func.coalesce(func.sum(ApiUsage.est_cost), 0))) or 0)


async def metrics_summary(session: AsyncSession, bootstrap_servers: str) -> MetricsSummary:
    lag = await consumer_lag(bootstrap_servers)
    backlog = await session.scalar(
        select(func.count()).select_from(OutboxEvents).where(OutboxEvents.published_at.is_(None))
    )
    dlq_open = await session.scalar(
        select(func.count()).select_from(DeadLetters).where(DeadLetters.status == "open")
    )
    return MetricsSummary(
        consumer_lag=lag,
        outbox_backlog=int(backlog or 0),
        dlq_open=int(dlq_open or 0),
        credits_used=round(await _credits_used(session), 4),
    )


async def usage(session: AsyncSession, from_: datetime | None, to: datetime | None) -> UsageOut:
    """``api_usage`` aggregated per provider / operation / unit type inside ``[from, to]``.

    ``credits_used`` is the cost inside the window; ``remaining_budget`` is the all-time budget
    left (the same figure the run estimate checks), null when ``BUDGET_CREDITS`` is unset.
    """
    conditions: list[Any] = []
    if from_ is not None:
        conditions.append(ApiUsage.created_at >= from_)
    if to is not None:
        conditions.append(ApiUsage.created_at <= to)
    rows = (
        await session.execute(
            select(
                ApiUsage.provider,
                ApiUsage.operation,
                ApiUsage.unit_type,
                func.sum(ApiUsage.units),
                func.sum(ApiUsage.est_cost),
            )
            .where(*conditions)
            .group_by(ApiUsage.provider, ApiUsage.operation, ApiUsage.unit_type)
            .order_by(ApiUsage.provider, ApiUsage.operation, ApiUsage.unit_type)
        )
    ).all()
    items = [
        UsageRow(
            provider=cast("Any", provider),
            operation=operation,
            unit_type=cast("Any", unit_type),
            units=float(units),
            est_cost=None if cost is None else float(cost),
        )
        for provider, operation, unit_type, units, cost in rows
    ]
    return UsageOut(
        items=items,
        credits_used=round(sum(i.est_cost or 0.0 for i in items), 4),
        budget_credits=budget_credits(),
        remaining_budget=remaining_budget(await _credits_used(session)),
    )
