"""Sink delivery: log row first, then ``handle`` (docs/10 section 1.3).

The delivery row for ``(integration, event, direction)`` is claimed *before* the connector is
called. A row already ``succeeded`` or ``skipped`` is returned untouched, so a replayed event never
posts twice. Retryable errors are recorded (attempt counted) and re-raised so the consumer sends
the event through the retry topics; permanent errors are recorded as ``failed`` and swallowed.

``DeliveryStore`` is the persistence seam. ``InMemoryDeliveryStore`` is a complete implementation
(used by tests and single-process runs); the SQL store over ``integration_deliveries`` lands with
the API-01 models and implements the same protocol.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pareeksha.events.schemas import AnyEnvelope
from pareeksha.integrations.base import (
    Connector,
    ConnectorPermanentError,
    ConnectorRetryableError,
    DeliveryCtx,
    DeliveryOutcome,
    EvaluationSummary,
)
from pareeksha.integrations.crypto import SecretBox, SecretDecryptError

Direction = Literal["inbound", "outbound"]
TERMINAL = ("succeeded", "skipped")


@dataclass
class DeliveryRecord:
    id: uuid.UUID
    integration_id: uuid.UUID
    event_id: uuid.UUID
    direction: Direction
    status: str = "pending"
    attempts: int = 0
    http_status: int | None = None
    external_id: str | None = None
    request_summary: dict[str, Any] = field(default_factory=dict)
    response_excerpt: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DeliveryStore(Protocol):
    def claim(
        self, integration_id: uuid.UUID, event_id: uuid.UUID, direction: Direction
    ) -> tuple[DeliveryRecord, bool]:
        """Return the unique row for the key and whether this call created it."""

    def save(self, record: DeliveryRecord) -> None: ...

    def recent(self, integration_id: uuid.UUID, limit: int = 100) -> list[DeliveryRecord]: ...


class InMemoryDeliveryStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[uuid.UUID, uuid.UUID, str], DeliveryRecord] = {}

    def claim(
        self, integration_id: uuid.UUID, event_id: uuid.UUID, direction: Direction
    ) -> tuple[DeliveryRecord, bool]:
        key = (integration_id, event_id, direction)
        existing = self._rows.get(key)
        if existing is not None:
            return existing, False
        record = DeliveryRecord(uuid.uuid4(), integration_id, event_id, direction)
        self._rows[key] = record
        return record, True

    def save(self, record: DeliveryRecord) -> None:
        record.updated_at = datetime.now(UTC)
        self._rows[(record.integration_id, record.event_id, record.direction)] = record

    def recent(self, integration_id: uuid.UUID, limit: int = 100) -> list[DeliveryRecord]:
        rows = [r for r in self._rows.values() if r.integration_id == integration_id]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]


@dataclass(frozen=True)
class IntegrationRecord:
    """An ``integrations`` row as the delivery service needs it."""

    id: uuid.UUID
    connector: str
    config: dict[str, Any]
    secrets_encrypted: str
    enabled: bool = True


class DeliveryService:
    def __init__(self, store: DeliveryStore, box: SecretBox) -> None:
        self.store = store
        self.box = box

    async def deliver(
        self,
        connector: Connector,
        integration: IntegrationRecord,
        event: AnyEnvelope,
        *,
        summary: EvaluationSummary | None = None,
        public_base_url: str | None = None,
    ) -> DeliveryRecord:
        record, _created = self.store.claim(integration.id, event.event_id, "outbound")
        if record.status in TERMINAL:
            return record
        record.attempts += 1
        record.request_summary = {"event_type": event.type.value}
        ctx = DeliveryCtx(
            integration_id=integration.id,
            delivery_id=record.id,
            attempt=record.attempts,
            public_base_url=public_base_url,
            summary=summary,
        )
        try:
            config = connector.config_schema.model_validate(integration.config)
            secrets = connector.secrets_schema.model_validate(
                self.box.decrypt(integration.secrets_encrypted)
            )
            outcome = await connector.handle(event, config, secrets, ctx)
        except ConnectorRetryableError as exc:
            record.status = "pending"
            record.response_excerpt = str(exc)[:2000]
            self.store.save(record)
            raise
        except (
            ConnectorPermanentError,
            SecretDecryptError,
            ValueError,
        ) as exc:  # ValueError: pydantic
            record.status = "failed"
            record.response_excerpt = str(exc)[:2000]
            self.store.save(record)
            return record
        _apply(record, outcome)
        self.store.save(record)
        return record


def _apply(record: DeliveryRecord, outcome: DeliveryOutcome) -> None:
    record.status = outcome.status
    record.http_status = outcome.http_status
    record.external_id = outcome.external_id
    record.response_excerpt = outcome.response_excerpt or outcome.detail or None
