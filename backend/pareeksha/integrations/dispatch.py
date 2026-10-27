"""Fan an ``evaluation.completed`` / ``run.completed`` event out to the project's sink integrations.

Used by the ``integrations`` Kafka consumer (``workers/integrations.py``) and by the redeliver
route. All reads go through psycopg on the connection passed in; all delivery rows go through the
``DeliveryStore`` (an autocommit connection of its own, see ``sql_store.py``).

``EvaluationSummary`` is rebuilt from the database at delivery time: it never travels in the Kafka
event, carries no transcript or audio, and ``calls.metadata`` (phone/email/CRM ids) is read only
here, for the sinks that need it to find the contact (docs/10 section 1.4).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from pareeksha.events.schemas import AnyEnvelope, EvaluationCompleted, RunCompleted, parse_envelope
from pareeksha.integrations.base import (
    Connector,
    ConnectorRetryableError,
    EvaluationSummary,
    TopFailingDimension,
)
from pareeksha.integrations.crypto import SecretBox
from pareeksha.integrations.delivery import (
    DeliveryRecord,
    DeliveryService,
    DeliveryStore,
    IntegrationRecord,
)
from pareeksha.integrations.registry import ConnectorRegistry
from pareeksha.integrations.sql_store import PsycopgDeliveryStore

log = logging.getLogger(__name__)

DEFAULT_EVENTS = ["evaluation.completed"]
#: A dimension scored at or below this is reported as failing (scores are 0-4).
FAILING_SCORE = 2
MAX_FAILING_DIMENSIONS = 3


@dataclass(frozen=True, slots=True)
class SinkIntegration:
    record: IntegrationRecord
    event_filter: dict[str, Any]


class DeliveryRetry(Exception):
    """At least one integration hit a retryable error; the event must be retried."""


def web_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")


def filter_matches(
    event_filter: dict[str, Any],
    event: AnyEnvelope,
) -> bool:
    """Apply an integration's ``event_filter`` (events, agent_ids, only_failed, min_score_below)."""
    events = event_filter.get("events") or DEFAULT_EVENTS
    if event.type.value not in events:
        return False
    payload = event.payload
    if isinstance(payload, EvaluationCompleted):
        agent_ids = event_filter.get("agent_ids") or []
        if agent_ids and str(payload.agent_id) not in {str(a) for a in agent_ids}:
            return False
        if event_filter.get("only_failed") and payload.passed is not False:
            return False
        below = event_filter.get("min_score_below")
        if below is not None and (payload.overall_score is None or payload.overall_score >= below):
            return False
    elif isinstance(payload, RunCompleted):
        agent_ids = event_filter.get("agent_ids") or []
        if agent_ids and str(payload.agent_id) not in {str(a) for a in agent_ids}:
            return False
    return True


async def project_of(conn: psycopg.AsyncConnection[Any], event: AnyEnvelope) -> uuid.UUID | None:
    payload = event.payload
    if isinstance(payload, EvaluationCompleted):
        sql, key = "SELECT project_id FROM calls WHERE id = %s", payload.call_id
    elif isinstance(payload, RunCompleted):
        sql, key = "SELECT project_id FROM test_runs WHERE id = %s", payload.run_id
    else:
        return None
    cur = await conn.execute(sql, (key,))
    row = await cur.fetchone()
    return None if row is None else uuid.UUID(str(row[0]))


async def load_sinks(
    conn: psycopg.AsyncConnection[Any], project_id: uuid.UUID, box: SecretBox
) -> list[SinkIntegration]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, connector, config, secrets_encrypted, event_filter, enabled "
            "FROM integrations WHERE project_id = %s AND enabled AND direction IN ('sink', 'both') "
            "ORDER BY created_at, id",
            (project_id,),
        )
        rows = await cur.fetchall()
    sinks: list[SinkIntegration] = []
    for row in rows:
        raw = row["secrets_encrypted"]
        token = bytes(raw).decode() if raw is not None else box.encrypt({})
        sinks.append(
            SinkIntegration(
                IntegrationRecord(
                    id=row["id"],
                    connector=row["connector"],
                    config=row["config"] or {},
                    secrets_encrypted=token,
                    enabled=row["enabled"],
                ),
                row["event_filter"] or {},
            )
        )
    return sinks


async def build_summary(
    conn: psycopg.AsyncConnection[Any], evaluation_id: uuid.UUID
) -> EvaluationSummary | None:
    """The sink-facing summary of one evaluation, or ``None`` when it does not exist."""
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT e.call_id, e.overall_score, e.passed, e.critical_failure, e.failure_types, "
            "e.summary, e.dimensions, c.agent_id, a.name AS agent_name, c.source, c.language, "
            "c.duration_ms, c.metadata, s.title AS scenario, p.name AS persona "
            "FROM evaluations e JOIN calls c ON c.id = e.call_id "
            "LEFT JOIN agents a ON a.id = c.agent_id "
            "LEFT JOIN run_items ri ON ri.id = c.run_item_id "
            "LEFT JOIN scenarios s ON s.id = ri.scenario_id "
            "LEFT JOIN personas p ON p.id = ri.persona_id "
            "WHERE e.id = %s",
            (evaluation_id,),
        )
        row = await cur.fetchone()
    if row is None:
        return None
    metadata = {str(k): str(v) for k, v in (row["metadata"] or {}).items()}
    return EvaluationSummary(
        call_id=row["call_id"],
        agent_id=row["agent_id"],
        agent_name=row["agent_name"],
        source=row["source"],
        external_id=metadata.get("external_id"),
        scenario=row["scenario"],
        persona=row["persona"],
        language=row["language"],
        duration_ms=row["duration_ms"],
        overall_score=None if row["overall_score"] is None else float(row["overall_score"]),
        passed=row["passed"],
        critical_failure=row["critical_failure"],
        failure_types=list(row["failure_types"] or []),
        summary=row["summary"] or "",
        top_failing_dimensions=_failing(row["dimensions"] or {}),
        link=f"{web_base_url()}/calls/{row['call_id']}",
        metadata=metadata,
    )


def _failing(dimensions: dict[str, Any]) -> list[TopFailingDimension]:
    scored = [
        (int(d["score"]), key, str(d.get("reason", "")))
        for key, d in dimensions.items()
        if isinstance(d, dict) and isinstance(d.get("score"), int)
    ]
    worst = sorted(s for s in scored if s[0] <= FAILING_SCORE)[:MAX_FAILING_DIMENSIONS]
    return [TopFailingDimension(dimension=k, score=sc, reason=r) for sc, k, r in worst]


async def summary_for(
    conn: psycopg.AsyncConnection[Any], event: AnyEnvelope
) -> EvaluationSummary | None:
    """The summary for an ``evaluation.completed`` event; ``None`` for other event types."""
    payload = event.payload
    if not isinstance(payload, EvaluationCompleted):
        return None
    summary = await build_summary(conn, payload.evaluation_id)
    if summary is None:
        raise LookupError(f"evaluation {payload.evaluation_id} not found")
    return summary


async def deliver_to_sinks(
    conn: psycopg.AsyncConnection[Any],
    store: DeliveryStore,
    box: SecretBox,
    registry: ConnectorRegistry,
    event: AnyEnvelope,
    *,
    final_attempt: bool,
) -> list[DeliveryRecord]:
    """Deliver ``event`` to every matching sink. Raises ``DeliveryRetry`` after trying them all
    when any was retryable, so one slow endpoint never blocks the others."""
    project_id = await project_of(conn, event)
    if project_id is None:
        log.warning("no project for event %s; nothing to deliver", event.event_id)
        return []
    summary = await summary_for(conn, event)
    service = DeliveryService(store, box)
    delivered: list[DeliveryRecord] = []
    retry: list[str] = []
    for sink in await load_sinks(conn, project_id, box):
        if not filter_matches(sink.event_filter, event):
            continue
        connector = _connector(registry, sink.record.connector)
        if connector is None or event.type.value not in connector.subscribes_to:
            continue
        try:
            delivered.append(
                await service.deliver(
                    connector,
                    sink.record,
                    event,
                    summary=summary,
                    public_base_url=web_base_url(),
                    final_attempt=final_attempt,
                )
            )
        except ConnectorRetryableError as exc:
            retry.append(f"{sink.record.connector} {sink.record.id}: {exc}")
    if retry and not final_attempt:
        raise DeliveryRetry("; ".join(retry))
    return delivered


def _connector(registry: ConnectorRegistry, name: str) -> Connector | None:
    try:
        return registry.get(name)()
    except KeyError:
        log.warning("integration uses connector %r which is not installed; skipped", name)
        return None


class NothingToReplay(Exception):
    """The delivery row has no stored event (it predates event capture)."""


async def redeliver(
    conn: psycopg.AsyncConnection[Any],
    store: PsycopgDeliveryStore,
    box: SecretBox,
    registry: ConnectorRegistry,
    integration: IntegrationRecord,
    delivery_id: uuid.UUID,
) -> DeliveryRecord:
    """Send a logged delivery again (operator action): reset the row to ``pending`` and deliver.

    The original event comes from the row's ``request_summary``; the summary is rebuilt from the
    database, so the receiver gets the call's current data under the same event id. There is no
    retry topic behind this path, so a retryable failure is recorded as ``failed``.
    """
    record = await store.get(delivery_id)
    if record is None or record.integration_id != integration.id:
        raise LookupError(f"delivery {delivery_id} not found")
    stored = record.request_summary.get("envelope")
    if not isinstance(stored, dict):
        raise NothingToReplay(str(delivery_id))
    event = parse_envelope(stored)
    connector = _connector(registry, integration.connector)
    if connector is None:
        raise LookupError(f"connector {integration.connector!r} is not installed")
    record.status = "pending"
    await store.save(record)
    try:
        return await DeliveryService(store, box).deliver(
            connector,
            integration,
            event,
            summary=await summary_for(conn, event),
            public_base_url=web_base_url(),
            final_attempt=True,
        )
    except ConnectorRetryableError:
        refreshed = await store.get(delivery_id)
        assert refreshed is not None
        return refreshed
