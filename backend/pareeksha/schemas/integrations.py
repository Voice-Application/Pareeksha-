"""Integrations and webhooks (docs/06-api-spec.md section 8, docs/10 section 1-2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from pareeksha.schemas.common import RequestModel

ConnectorDirection = Literal["source", "sink", "both"]
DeliveryStatus = Literal["pending", "succeeded", "failed", "skipped"]


class ConnectorInfo(BaseModel):
    """An installed connector with JSON Schemas so the web app can render its forms."""

    name: str = Field(examples=["hubspot"])
    direction: ConnectorDirection
    subscribes_to: list[str] = Field(default_factory=list)
    config_schema: dict[str, Any]
    secrets_schema: dict[str, Any]


class EventFilter(BaseModel):
    events: list[str] = Field(default_factory=lambda: ["evaluation.completed"])
    agent_ids: list[UUID] = Field(default_factory=list)
    only_failed: bool = False
    min_score_below: float | None = None


class IntegrationCreate(RequestModel):
    connector: str = Field(examples=["hubspot"])
    name: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict, description="write-only")
    event_filter: EventFilter = Field(default_factory=EventFilter)
    enabled: bool = True


class IntegrationUpdate(RequestModel):
    """PATCH: secrets are replaced only if provided."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
    secrets: dict[str, str] | None = None
    event_filter: EventFilter | None = None
    enabled: bool | None = None


class IntegrationOut(BaseModel):
    id: UUID
    connector: str
    name: str
    direction: ConnectorDirection
    enabled: bool
    config: dict[str, Any]
    secrets_set: bool = Field(description="secret values are never returned")
    event_filter: EventFilter
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    created_at: datetime
    updated_at: datetime
    inbound_url: str | None = Field(default=None, description="webhook integrations only")
    signing_secret: str | None = Field(
        default=None, description="webhook integrations: returned once, on creation"
    )


class IntegrationTestResult(BaseModel):
    ok: bool
    detail: str = ""


class DeliveryOut(BaseModel):
    id: UUID
    event_id: UUID
    direction: Literal["inbound", "outbound"]
    status: DeliveryStatus
    http_status: int | None = None
    external_id: str | None = None
    attempts: int
    response_excerpt: str | None = None
    created_at: datetime


class InboundCallPayload(BaseModel):
    """Body of ``POST /webhooks/inbound/{integration_id}`` (HMAC-signed, no API key)."""

    external_id: str = Field(min_length=1, examples=["exotel-CA123"])
    recording_url: str = Field(min_length=1, examples=["https://recordings.example.com/CA123.mp3"])
    agent_name: str | None = Field(default=None, examples=["EMI Reminder Bot"])
    language: str = Field(examples=["kn-IN"])
    metadata: dict[str, str] = Field(default_factory=dict)


class InboundAccepted(BaseModel):
    call_id: UUID
    duplicate: bool
