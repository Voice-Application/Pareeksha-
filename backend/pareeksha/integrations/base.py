"""Connector interface. FROZEN CONTRACT (docs/10-integrations-and-dx.md section 1.1, AGENTS.md 6.3).

A connector is a class discovered through the Python entry-point group ``pareeksha.connectors``:

    [project.entry-points."pareeksha.connectors"]
    zoho = "pareeksha_connector_zoho:ZohoConnector"

Sinks react to platform events (``handle``); sources turn inbound webhooks into audit requests
(``ingest``). The framework (INT-01) validates ``config`` / ``secrets`` against the connector's
schemas, encrypts secrets, writes the ``integration_deliveries`` row *before* calling ``handle`` so
a replayed event cannot post twice, and routes retryable failures through the retry topics.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from pareeksha.events.schemas import AnyEnvelope

#: Python entry-point group that third-party connector packages register under.
CONNECTOR_ENTRY_POINT_GROUP = "pareeksha.connectors"

ConnectorDirection = Literal["source", "sink", "both"]
DeliveryStatus = Literal["succeeded", "failed", "skipped"]


class ConnectorError(Exception):
    """Base class for connector failures."""


class ConnectorRetryableError(ConnectorError):
    """Timeouts, 5xx and 429: retried via the retry topics; after 3 attempts -> DLQ."""

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class ConnectorPermanentError(ConnectorError):
    """Bad config, auth failure, 4xx. Not retried; the delivery is recorded as failed."""


class ConnectorDirectionError(ConnectorPermanentError):
    """``handle`` called on a source-only connector, or ``ingest`` on a sink-only one."""


class TestResult(BaseModel):
    """Result of ``Connector.test`` (``POST /integrations/{id}/test``)."""

    __test__ = False  # not a pytest class despite the name

    ok: bool
    detail: str = ""


class InboundRequest(BaseModel):
    """A raw inbound webhook as handed to a source connector."""

    headers: dict[str, str]
    body: bytes
    integration_id: str


class AuditRequest(BaseModel):
    """What a source turns an inbound call into (becomes ``audit.requested``)."""

    recording_url: str
    agent_id: str | None = None
    agent_name: str | None = None
    language: str = Field(description='e.g. "kn-IN" or "kn-IN,en-IN"')
    external_id: str = Field(description="dedupe key in external_refs")
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="phone/email/crm ids, used to match the contact on the way back",
    )


class TopFailingDimension(BaseModel):
    dimension: str
    score: int = Field(ge=0, le=4)
    reason: str


class EvaluationSummary(BaseModel):
    """What sinks receive for an evaluation. No transcript or audio (data minimisation, 10 s1.4).

    ``metadata`` is the call's CRM-matching metadata (phone/email/ids). It is never sent to the
    judge, but sinks need it to find the contact.
    """

    model_config = ConfigDict(extra="forbid")

    call_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    agent_name: str | None = None
    source: Literal["simulation", "upload", "import"]
    external_id: str | None = None
    scenario: str | None = None
    persona: str | None = None
    language: str | None = None
    duration_ms: int | None = None
    overall_score: float | None = Field(default=None, ge=0, le=100)
    passed: bool | None = None
    critical_failure: bool = False
    failure_types: list[str] = Field(default_factory=list)
    summary: str = ""
    top_failing_dimensions: list[TopFailingDimension] = Field(default_factory=list, max_length=3)
    link: str = Field(description="deep link to the call in the web app")
    metadata: dict[str, str] = Field(default_factory=dict)


class DeliveryCtx(BaseModel):
    """Per-delivery context built by the framework for ``Connector.handle``."""

    integration_id: uuid.UUID
    delivery_id: uuid.UUID
    attempt: int = Field(ge=1)
    public_base_url: str | None = None
    #: Present for ``evaluation.completed`` events; ``None`` for ``run.completed``.
    summary: EvaluationSummary | None = None


class DeliveryOutcome(BaseModel):
    """What ``handle`` reports; the framework stores it on the delivery row."""

    status: DeliveryStatus
    http_status: int | None = None
    #: e.g. the HubSpot note id.
    external_id: str | None = None
    response_excerpt: str | None = Field(default=None, max_length=2000)
    #: Reason for ``skipped`` (e.g. "no matching contact"); skipped is not an error.
    detail: str = ""


class Connector(ABC):
    """Base class every connector implements.

    Class-level attributes describe the connector; subclasses must set all of them. ``test`` is
    mandatory. A sink overrides ``handle``; a source overrides ``ingest``; ``both`` overrides both.
    """

    name: ClassVar[str]
    direction: ClassVar[ConnectorDirection]
    #: Non-secret settings.
    config_schema: ClassVar[type[BaseModel]]
    #: Tokens, signing secrets (encrypted at rest, never returned by the API).
    secrets_schema: ClassVar[type[BaseModel]]
    #: Sinks: event types this connector reacts to, e.g. ``["evaluation.completed"]``.
    subscribes_to: ClassVar[list[str]]

    @abstractmethod
    async def test(self, config: BaseModel, secrets: BaseModel) -> TestResult:
        """Check credentials / reachability without side effects."""

    async def handle(
        self, event: AnyEnvelope, config: BaseModel, secrets: BaseModel, ctx: DeliveryCtx
    ) -> DeliveryOutcome:
        """Sink: react to a platform event. Must be idempotent for the same (integration, event)."""
        raise ConnectorDirectionError(f"connector {self.name!r} is not a sink")

    async def ingest(
        self, request: InboundRequest, config: BaseModel, secrets: BaseModel
    ) -> list[AuditRequest]:
        """Source: turn an inbound webhook into audit requests (signature already verified)."""
        raise ConnectorDirectionError(f"connector {self.name!r} is not a source")


_VALID_DIRECTIONS = ("source", "sink", "both")


def validate_connector_class(cls: type[Any]) -> list[str]:
    """Return the list of contract violations of a connector class (empty = valid).

    The registry (INT-01) calls this on every entry point and refuses classes with problems.
    """
    problems: list[str] = []
    if not (isinstance(cls, type) and issubclass(cls, Connector)):
        return [f"{cls!r} is not a subclass of Connector"]
    if getattr(cls, "__abstractmethods__", None):
        problems.append(f"abstract methods not implemented: {sorted(cls.__abstractmethods__)}")
    name = getattr(cls, "name", None)
    if not isinstance(name, str) or not name or name != name.lower() or " " in name:
        problems.append("name must be a non-empty lowercase string without spaces")
    direction = getattr(cls, "direction", None)
    if direction not in _VALID_DIRECTIONS:
        problems.append(f"direction must be one of {_VALID_DIRECTIONS}")
    for attr in ("config_schema", "secrets_schema"):
        schema = getattr(cls, attr, None)
        if not (isinstance(schema, type) and issubclass(schema, BaseModel)):
            problems.append(f"{attr} must be a pydantic BaseModel subclass")
    subscribes = getattr(cls, "subscribes_to", None)
    if not isinstance(subscribes, list) or not all(isinstance(s, str) for s in subscribes):
        problems.append("subscribes_to must be a list of event type strings")
    elif direction in ("sink", "both") and not subscribes:
        problems.append("sinks must subscribe to at least one event type")
    if direction in ("sink", "both") and cls.handle is Connector.handle:
        problems.append("sink connectors must override handle()")
    if direction in ("source", "both") and cls.ingest is Connector.ingest:
        problems.append("source connectors must override ingest()")
    return problems
