"""Event envelope and payload schemas. FROZEN CONTRACT (docs/03-TRD.md 10.3, AGENTS.md 6.1).

These Pydantic models are the source of truth for every Kafka message. Payloads carry IDs and
small facts only; transcripts and audio stay in Postgres / blob storage. There is no schema
registry in v1: the models plus the envelope ``version`` field are the contract.

Changing a field, a type, or a key is a contract change (Tech Lead approval + CHANGELOG entry).
Adding a backwards-incompatible change requires a new envelope ``version`` and a new topic suffix.
"""

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Generic, Literal, TypeVar

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    model_validator,
)

from pareeksha.events.topics import MAX_ATTEMPTS, TOPIC_SPECS, Topics

ENVELOPE_VERSION = 1


class EventType(StrEnum):
    """Envelope ``type`` values."""

    RUN_REQUESTED = "run.requested"
    CALL_REQUESTED = "call.requested"
    AUDIT_REQUESTED = "audit.requested"
    CALL_COMPLETED = "call.completed"
    EVALUATION_COMPLETED = "evaluation.completed"
    RUN_COMPLETED = "run.completed"
    PROGRESS = "progress"
    SCENARIO_GENERATE_REQUESTED = "scenario.generate.requested"
    DIALECT_CLIP_REQUESTED = "dialect.clip.requested"


# ---------------------------------------------------------------------------------------------
# Shared enums (string literals mirror docs/schema.sql CHECK constraints)
# ---------------------------------------------------------------------------------------------

RunKind = Literal["matrix", "regression", "dry_run"]
CallSource = Literal["simulation", "upload", "import"]
EndReason = Literal[
    "goal_achieved",
    "gave_up",
    "agent_hangup",
    "max_turns",
    "timeout",
    "agent_silent",
    "connect_failed",
    "cancelled",
    "infra_error",
    "upload",
    "import",
]
RunFinalStatus = Literal["completed", "partial", "cancelled", "failed"]
RegressionStatus = Literal["blocking", "scheduled", "manual", "retired"]
EvaluationStatus = Literal["ok", "judge_error"]


class EventPayload(BaseModel, ABC):
    """Base class for every event payload.

    Subclasses declare which event type and topic they belong to and how they are keyed.
    """

    model_config = ConfigDict(extra="forbid")

    event_type: ClassVar[EventType]
    topic: ClassVar[Topics]

    @abstractmethod
    def partition_key(self) -> str:
        """Kafka message key for this payload (see TOPIC_SPECS for the rule per topic)."""


P = TypeVar("P", bound=EventPayload)


# ---------------------------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------------------------


class RunRequested(EventPayload):
    """API (outbox) -> planner. Key: run_id.

    For ``kind`` in matrix/dry_run the planner expands scenario x persona x noise profile x repeats.
    For ``kind == "regression"`` the planner resolves regression tests by ``regression_statuses``.
    """

    event_type: ClassVar[EventType] = EventType.RUN_REQUESTED
    topic: ClassVar[Topics] = Topics.RUN_REQUESTED

    run_id: uuid.UUID
    agent_id: uuid.UUID
    kind: RunKind
    scenario_ids: list[uuid.UUID] = Field(default_factory=list)
    persona_ids: list[uuid.UUID] = Field(default_factory=list)
    noise_profile_ids: list[uuid.UUID] = Field(default_factory=list)
    repeats: int = Field(default=1, ge=1, le=20)
    seed: int = 0
    regression_statuses: list[RegressionStatus] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_shape(self) -> RunRequested:
        if self.kind == "regression":
            if not self.regression_statuses:
                raise ValueError("regression runs need at least one regression status")
        elif not (self.scenario_ids and self.persona_ids and self.noise_profile_ids):
            raise ValueError("matrix runs need scenario_ids, persona_ids and noise_profile_ids")
        return self

    def partition_key(self) -> str:
        return str(self.run_id)


class CallRequested(EventPayload):
    """planner / API -> simulator. Key: run_item_id (spreads a run over partitions)."""

    event_type: ClassVar[EventType] = EventType.CALL_REQUESTED
    topic: ClassVar[Topics] = Topics.CALL_REQUESTED

    run_id: uuid.UUID
    run_item_id: uuid.UUID
    agent_id: uuid.UUID
    scenario_id: uuid.UUID
    persona_id: uuid.UUID
    noise_profile_id: uuid.UUID
    seed: int
    regression_test_id: uuid.UUID | None = None

    def partition_key(self) -> str:
        return str(self.run_item_id)


class AuditRequested(EventPayload):
    """API (upload) or a source connector (import) -> auditor. Key: call_id."""

    event_type: ClassVar[EventType] = EventType.AUDIT_REQUESTED
    topic: ClassVar[Topics] = Topics.AUDIT_REQUESTED

    call_id: uuid.UUID
    source: Literal["upload", "import"]
    agent_id: uuid.UUID | None = None
    language: str = Field(min_length=2, examples=["kn-IN", "kn-IN,en-IN"])
    #: Blob path (uploads) or SSRF-checked https URL (imports).
    recording_ref: str = Field(min_length=1)
    stereo_channels_are_speakers: bool = False
    integration_id: uuid.UUID | None = None
    external_id: str | None = None

    @model_validator(mode="after")
    def _check_source(self) -> AuditRequested:
        if self.source == "import" and not (self.integration_id and self.external_id):
            raise ValueError("imported calls need integration_id and external_id")
        return self

    def partition_key(self) -> str:
        return str(self.call_id)


class CallCompleted(EventPayload):
    """simulator / auditor -> evaluator. Key: call_id."""

    event_type: ClassVar[EventType] = EventType.CALL_COMPLETED
    topic: ClassVar[Topics] = Topics.CALL_COMPLETED

    call_id: uuid.UUID
    source: CallSource
    agent_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    run_item_id: uuid.UUID | None = None
    end_reason: EndReason | None = None

    @model_validator(mode="after")
    def _check_simulation(self) -> CallCompleted:
        if self.source == "simulation" and not (self.run_id and self.run_item_id):
            raise ValueError("simulated calls need run_id and run_item_id")
        return self

    def partition_key(self) -> str:
        return str(self.call_id)


class EvaluationCompleted(EventPayload):
    """evaluator -> finalizer, integrations. Key: call_id."""

    event_type: ClassVar[EventType] = EventType.EVALUATION_COMPLETED
    topic: ClassVar[Topics] = Topics.EVALUATION_COMPLETED

    call_id: uuid.UUID
    evaluation_id: uuid.UUID
    status: EvaluationStatus = "ok"
    agent_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    run_item_id: uuid.UUID | None = None
    overall_score: float | None = Field(default=None, ge=0, le=100)
    passed: bool | None = None
    critical_failure: bool = False
    needs_human_review: bool = False
    failure_types: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_scored(self) -> EvaluationCompleted:
        if self.status == "ok" and (self.overall_score is None or self.passed is None):
            raise ValueError("status=ok requires overall_score and passed")
        return self

    def partition_key(self) -> str:
        return str(self.call_id)


class RunCompletedSummary(BaseModel):
    """Small facts only; the full summary lives in ``test_runs.summary``."""

    model_config = ConfigDict(extra="forbid")

    item_count: int = Field(ge=0)
    evaluated_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    pass_rate: float | None = Field(default=None, ge=0, le=1)
    critical_failures: int = Field(default=0, ge=0)
    needs_review: int = Field(default=0, ge=0)
    score_mean: float | None = Field(default=None, ge=0, le=100)
    suite_passed: bool | None = None  # regression runs only


class RunCompleted(EventPayload):
    """finalizer -> integrations (emitted exactly once per run). Key: run_id."""

    event_type: ClassVar[EventType] = EventType.RUN_COMPLETED
    topic: ClassVar[Topics] = Topics.RUN_COMPLETED

    run_id: uuid.UUID
    agent_id: uuid.UUID
    kind: RunKind
    status: RunFinalStatus
    summary: RunCompletedSummary

    def partition_key(self) -> str:
        return str(self.run_id)


ProgressKind = Literal["item.status", "call.evaluated", "run.completed"]


class ProgressEvent(EventPayload):
    """Any worker -> api SSE. Key: run_id when known, else call_id.

    ``kind`` maps 1:1 to the SSE event names of ``GET /runs/{id}/events``.
    """

    event_type: ClassVar[EventType] = EventType.PROGRESS
    topic: ClassVar[Topics] = Topics.PROGRESS

    kind: ProgressKind
    run_id: uuid.UUID | None = None
    call_id: uuid.UUID | None = None
    run_item_id: uuid.UUID | None = None
    status: str | None = None  # item.status
    scenario: str | None = None  # item.status
    persona: str | None = None  # item.status
    overall_score: float | None = Field(default=None, ge=0, le=100)  # call.evaluated
    passed: bool | None = None  # call.evaluated
    critical_failure: bool | None = None  # call.evaluated
    pass_rate: float | None = Field(default=None, ge=0, le=1)  # run.completed
    critical_failures: int | None = Field(default=None, ge=0)  # run.completed

    @model_validator(mode="after")
    def _check_kind(self) -> ProgressEvent:
        if self.run_id is None and self.call_id is None:
            raise ValueError("progress events need run_id or call_id")
        if self.kind == "item.status" and not (self.run_item_id and self.status):
            raise ValueError("item.status needs run_item_id and status")
        if self.kind == "call.evaluated" and not (
            self.call_id and self.overall_score is not None and self.passed is not None
        ):
            raise ValueError("call.evaluated needs call_id, overall_score and passed")
        if self.kind == "run.completed" and not self.run_id:
            raise ValueError("run.completed needs run_id")
        return self

    def partition_key(self) -> str:
        return str(self.run_id or self.call_id)


class ScenarioGenerateRequested(EventPayload):
    """API (outbox) -> generator. Key: agent_id."""

    event_type: ClassVar[EventType] = EventType.SCENARIO_GENERATE_REQUESTED
    topic: ClassVar[Topics] = Topics.SCENARIO_GENERATE_REQUESTED

    draft_id: uuid.UUID
    agent_id: uuid.UUID
    count: int = Field(ge=1, le=50)
    mix: dict[str, int] = Field(default_factory=dict)  # e.g. {"happy_path": 3, "edge_case": 4}

    def partition_key(self) -> str:
        return str(self.agent_id)


class DialectClipRequested(EventPayload):
    """API (outbox) -> dialect. One message per clip x condition. Key: sample_id."""

    event_type: ClassVar[EventType] = EventType.DIALECT_CLIP_REQUESTED
    topic: ClassVar[Topics] = Topics.DIALECT_CLIP_REQUESTED

    report_id: uuid.UUID
    dataset_id: uuid.UUID
    sample_id: uuid.UUID
    noise_profile_id: uuid.UUID
    engines: list[str] = Field(min_length=1, examples=[["gnani-prisma"]])
    #: Total asr_results the report waits for (clips x conditions x engines).
    expected_results: int = Field(ge=1)

    def partition_key(self) -> str:
        return str(self.sample_id)


#: Every payload class, in a stable order.
PAYLOAD_MODELS: tuple[type[EventPayload], ...] = (
    RunRequested,
    CallRequested,
    AuditRequested,
    CallCompleted,
    EvaluationCompleted,
    RunCompleted,
    ProgressEvent,
    ScenarioGenerateRequested,
    DialectClipRequested,
)
EVENT_PAYLOADS: dict[EventType, type[EventPayload]] = {m.event_type: m for m in PAYLOAD_MODELS}
EVENT_TOPIC: dict[EventType, Topics] = {m.event_type: m.topic for m in PAYLOAD_MODELS}


# ---------------------------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------------------------


class Envelope(BaseModel, Generic[P]):
    """The JSON object in every Kafka message value (UTF-8).

    Handlers are typed ``Envelope[CallCompleted]``; generic code uses ``AnyEnvelope``.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    type: EventType
    version: Annotated[int, Field(ge=1)] = ENVELOPE_VERSION
    occurred_at: AwareDatetime
    correlation_id: str = Field(min_length=1, description="run_id or call_id")
    causation_id: str | None = Field(
        default=None, description="event_id of the event that caused this one"
    )
    attempt: int = Field(default=1, ge=1, le=MAX_ATTEMPTS + 1)
    producer: str = Field(min_length=1, description="e.g. simulator@host-3")
    payload: SerializeAsAny[P]

    @model_validator(mode="before")
    @classmethod
    def _resolve_payload(cls, data: Any) -> Any:
        """Validate a raw payload dict with the model registered for the envelope ``type``."""
        if isinstance(data, dict) and isinstance(data.get("payload"), dict):
            try:
                event_type = EventType(str(data.get("type")))
            except ValueError as exc:
                raise UnknownEventTypeError(f"unknown event type: {data.get('type')!r}") from exc
            data = {**data, "payload": EVENT_PAYLOADS[event_type].model_validate(data["payload"])}
        return data

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Envelope[P]:
        expected = EVENT_PAYLOADS[self.type]
        if not isinstance(self.payload, expected):
            raise ValueError(
                f"payload {type(self.payload).__name__} does not match type {self.type}"
            )
        return self

    @property
    def topic(self) -> Topics:
        return EVENT_TOPIC[self.type]

    def partition_key(self) -> str:
        return self.payload.partition_key()

    def to_json_bytes(self) -> bytes:
        """Serialise as the Kafka message value."""
        return self.model_dump_json().encode("utf-8")


AnyEnvelope = Envelope[EventPayload]


class UnknownEventTypeError(ValueError):
    """The envelope ``type`` is not part of the contract (permanent error: send to the DLQ)."""


def parse_envelope(raw: bytes | str | dict[str, Any]) -> AnyEnvelope:
    """Validate a raw message value into a typed envelope.

    Raises ``UnknownEventTypeError`` for an unknown ``type`` and pydantic ``ValidationError`` for
    any schema violation; both are permanent failures in the consumer framework.
    """
    data: dict[str, Any] = json.loads(raw) if isinstance(raw, (bytes, str)) else dict(raw)
    try:
        EventType(str(data.get("type")))
    except ValueError as exc:
        raise UnknownEventTypeError(f"unknown event type: {data.get('type')!r}") from exc
    return AnyEnvelope.model_validate(data)


def make_envelope(
    payload: EventPayload,
    *,
    producer: str,
    correlation_id: str,
    causation_id: str | uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    attempt: int = 1,
) -> AnyEnvelope:
    """Build an envelope whose ``type`` is derived from the payload class."""
    return AnyEnvelope(
        event_id=event_id or uuid.uuid4(),
        type=payload.event_type,
        occurred_at=occurred_at or datetime.now(UTC),
        correlation_id=correlation_id,
        causation_id=None if causation_id is None else str(causation_id),
        attempt=attempt,
        producer=producer,
        payload=payload,
    )


def deterministic_event_id(input_event_id: uuid.UUID, output_type: EventType | str) -> uuid.UUID:
    """Id of an output event: ``uuid5(input_event_id, output_type)`` (AGENTS.md 6.1).

    A worker that crashes after committing and is redelivered the input re-produces the *same*
    output event id, so downstream consumers deduplicate it via ``processed_events``.
    """
    return uuid.uuid5(input_event_id, str(EventType(output_type).value))


def event_json_schemas() -> dict[str, Any]:
    """JSON Schemas for external consumers (served by ``GET /events/schemas``).

    Returns ``{"envelope": <schema>, "events": {<type>: {topic, key, envelope_version,
    payload_schema}}}``. The envelope schema leaves ``payload`` open; validate the payload against
    the ``payload_schema`` of the event type named in the envelope.
    """
    events: dict[str, Any] = {}
    for event_type, payload_model in EVENT_PAYLOADS.items():
        topic = EVENT_TOPIC[event_type]
        events[event_type.value] = {
            "topic": topic.value,
            "key": TOPIC_SPECS[topic].key,
            "envelope_version": ENVELOPE_VERSION,
            "payload_schema": payload_model.model_json_schema(),
        }
    return {"envelope": AnyEnvelope.model_json_schema(), "events": events}


__all__ = [
    "ENVELOPE_VERSION",
    "EVENT_PAYLOADS",
    "EVENT_TOPIC",
    "PAYLOAD_MODELS",
    "AnyEnvelope",
    "AuditRequested",
    "CallCompleted",
    "CallRequested",
    "DialectClipRequested",
    "Envelope",
    "EvaluationCompleted",
    "EventPayload",
    "EventType",
    "ProgressEvent",
    "RunCompleted",
    "RunCompletedSummary",
    "RunRequested",
    "ScenarioGenerateRequested",
    "UnknownEventTypeError",
    "deterministic_event_id",
    "event_json_schemas",
    "make_envelope",
    "parse_envelope",
]
