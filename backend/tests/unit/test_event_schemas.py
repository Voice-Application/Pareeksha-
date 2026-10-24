"""Schema round-trip and validation tests for every event type (TL-01 contract)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from pareeksha.events.schemas import (
    EVENT_PAYLOADS,
    EVENT_TOPIC,
    PAYLOAD_MODELS,
    AuditRequested,
    CallCompleted,
    CallRequested,
    DialectClipRequested,
    Envelope,
    EvaluationCompleted,
    EventType,
    ProgressEvent,
    RunCompleted,
    RunRequested,
    ScenarioGenerateRequested,
    UnknownEventTypeError,
    deterministic_event_id,
    event_json_schemas,
    make_envelope,
    parse_envelope,
)
from pareeksha.events.topics import EVENT_TOPICS, TOPIC_SPECS, Topics

RUN = uuid.UUID("11111111-1111-4111-8111-111111111111")
ITEM = uuid.UUID("22222222-2222-4222-8222-222222222222")
CALL = uuid.UUID("33333333-3333-4333-8333-333333333333")
AGENT = uuid.UUID("44444444-4444-4444-8444-444444444444")
SCEN = uuid.UUID("55555555-5555-4555-8555-555555555555")
PERS = uuid.UUID("66666666-6666-4666-8666-666666666666")
NOISE = uuid.UUID("77777777-7777-4777-8777-777777777777")
EVAL = uuid.UUID("88888888-8888-4888-8888-888888888888")
SAMPLE = uuid.UUID("99999999-9999-4999-8999-999999999999")
INTEG = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")

# One valid sample payload per event type, plus the Kafka key it must produce.
SAMPLES: dict[EventType, tuple[dict[str, Any], uuid.UUID]] = {
    EventType.RUN_REQUESTED: (
        {
            "run_id": RUN,
            "agent_id": AGENT,
            "kind": "matrix",
            "scenario_ids": [SCEN],
            "persona_ids": [PERS],
            "noise_profile_ids": [NOISE],
            "repeats": 2,
            "seed": 42,
        },
        RUN,
    ),
    EventType.CALL_REQUESTED: (
        {
            "run_id": RUN,
            "run_item_id": ITEM,
            "agent_id": AGENT,
            "scenario_id": SCEN,
            "persona_id": PERS,
            "noise_profile_id": NOISE,
            "seed": 7,
        },
        ITEM,
    ),
    EventType.AUDIT_REQUESTED: (
        {
            "call_id": CALL,
            "source": "import",
            "agent_id": AGENT,
            "language": "kn-IN",
            "recording_ref": "https://recordings.example.com/CA123.mp3",
            "integration_id": INTEG,
            "external_id": "exotel-CA123",
        },
        CALL,
    ),
    EventType.CALL_COMPLETED: (
        {
            "call_id": CALL,
            "source": "simulation",
            "agent_id": AGENT,
            "run_id": RUN,
            "run_item_id": ITEM,
            "end_reason": "goal_achieved",
        },
        CALL,
    ),
    EventType.EVALUATION_COMPLETED: (
        {
            "call_id": CALL,
            "evaluation_id": EVAL,
            "agent_id": AGENT,
            "run_id": RUN,
            "run_item_id": ITEM,
            "overall_score": 40.0,
            "passed": False,
            "critical_failure": True,
            "needs_human_review": True,
            "failure_types": ["asr_misrecognition", "wrong_fact"],
        },
        CALL,
    ),
    EventType.RUN_COMPLETED: (
        {
            "run_id": RUN,
            "agent_id": AGENT,
            "kind": "matrix",
            "status": "completed",
            "summary": {
                "item_count": 8,
                "evaluated_count": 8,
                "error_count": 0,
                "pass_rate": 0.7,
                "critical_failures": 1,
                "needs_review": 2,
                "score_mean": 78.4,
            },
        },
        RUN,
    ),
    EventType.PROGRESS: (
        {
            "kind": "call.evaluated",
            "run_id": RUN,
            "call_id": CALL,
            "run_item_id": ITEM,
            "overall_score": 72.5,
            "passed": False,
            "critical_failure": False,
        },
        RUN,
    ),
    EventType.SCENARIO_GENERATE_REQUESTED: (
        {"draft_id": SAMPLE, "agent_id": AGENT, "count": 10, "mix": {"happy_path": 3}},
        AGENT,
    ),
    EventType.DIALECT_CLIP_REQUESTED: (
        {
            "report_id": EVAL,
            "dataset_id": RUN,
            "sample_id": SAMPLE,
            "noise_profile_id": NOISE,
            "engines": ["gnani-prisma"],
            "expected_results": 354,
        },
        SAMPLE,
    ),
}


def test_every_event_type_has_a_sample_and_a_payload_model() -> None:
    assert set(SAMPLES) == set(EventType)
    assert set(EVENT_PAYLOADS) == set(EventType)
    assert {m.event_type for m in PAYLOAD_MODELS} == set(EventType)


def test_every_event_topic_has_exactly_one_payload_type() -> None:
    by_topic: dict[Topics, list[EventType]] = {}
    for event_type, topic in EVENT_TOPIC.items():
        by_topic.setdefault(topic, []).append(event_type)
    assert set(by_topic) == set(EVENT_TOPICS)
    assert all(len(types) == 1 for types in by_topic.values())
    assert all(topic in TOPIC_SPECS for topic in by_topic)


@pytest.mark.parametrize("event_type", list(EventType))
def test_payload_round_trip_and_key(event_type: EventType) -> None:
    data, key = SAMPLES[event_type]
    model = EVENT_PAYLOADS[event_type]
    payload = model.model_validate(data)
    assert model.model_validate_json(payload.model_dump_json()) == payload
    assert payload.partition_key() == str(key)


@pytest.mark.parametrize("event_type", list(EventType))
def test_envelope_bytes_round_trip(event_type: EventType) -> None:
    data, key = SAMPLES[event_type]
    payload = EVENT_PAYLOADS[event_type].model_validate(data)
    cause = uuid.uuid4()
    envelope = make_envelope(
        payload, producer="simulator@host-3", correlation_id=str(RUN), causation_id=cause
    )
    raw = envelope.to_json_bytes()
    wire = json.loads(raw)
    assert set(wire) == {
        "event_id",
        "type",
        "version",
        "occurred_at",
        "correlation_id",
        "causation_id",
        "attempt",
        "producer",
        "payload",
    }
    assert wire["type"] == event_type.value
    assert wire["version"] == 1 and wire["attempt"] == 1
    assert wire["causation_id"] == str(cause)
    parsed = parse_envelope(raw)
    assert parsed == envelope
    assert type(parsed.payload) is EVENT_PAYLOADS[event_type]
    assert parsed.topic == EVENT_TOPIC[event_type]
    assert parsed.partition_key() == str(key)


def test_typed_envelope_validates_payload_dict() -> None:
    data, _ = SAMPLES[EventType.CALL_COMPLETED]
    raw = {
        "event_id": str(uuid.uuid4()),
        "type": "call.completed",
        "version": 1,
        "occurred_at": "2026-10-26T10:15:00Z",
        "correlation_id": str(RUN),
        "causation_id": None,
        "attempt": 1,
        "producer": "simulator@host-3",
        "payload": json.loads(json.dumps(data, default=str)),
    }
    typed = Envelope[CallCompleted].model_validate(raw)
    assert typed.payload.call_id == CALL


def test_call_requested_is_keyed_by_run_item_not_run() -> None:
    data, _ = SAMPLES[EventType.CALL_REQUESTED]
    payload = CallRequested.model_validate(data)
    assert payload.partition_key() == str(ITEM) != str(RUN)


def test_progress_key_falls_back_to_call_id() -> None:
    event = ProgressEvent(kind="call.evaluated", call_id=CALL, overall_score=50, passed=True)
    assert event.partition_key() == str(CALL)


@pytest.mark.parametrize("event_type", list(EventType))
def test_unknown_payload_field_is_rejected(event_type: EventType) -> None:
    data, _ = SAMPLES[event_type]
    with pytest.raises(ValidationError):
        EVENT_PAYLOADS[event_type].model_validate({**data, "surprise": 1})


@pytest.mark.parametrize("event_type", list(EventType))
def test_missing_required_field_is_rejected(event_type: EventType) -> None:
    data, _ = SAMPLES[event_type]
    model = EVENT_PAYLOADS[event_type]
    required = [name for name, f in model.model_fields.items() if f.is_required()]
    assert required, "every payload has at least one required field"
    for name in required:
        broken = {k: v for k, v in data.items() if k != name}
        with pytest.raises(ValidationError):
            model.model_validate(broken)


@pytest.mark.parametrize(
    ("model", "base", "change"),
    [
        (RunRequested, EventType.RUN_REQUESTED, {"kind": "weekly"}),
        (RunRequested, EventType.RUN_REQUESTED, {"repeats": 0}),
        (RunRequested, EventType.RUN_REQUESTED, {"scenario_ids": []}),
        (RunRequested, EventType.RUN_REQUESTED, {"kind": "regression"}),  # no statuses
        (RunRequested, EventType.RUN_REQUESTED, {"run_id": "not-a-uuid"}),
        (CallRequested, EventType.CALL_REQUESTED, {"seed": "x"}),
        (AuditRequested, EventType.AUDIT_REQUESTED, {"source": "simulation"}),
        (AuditRequested, EventType.AUDIT_REQUESTED, {"external_id": None}),  # import needs it
        (AuditRequested, EventType.AUDIT_REQUESTED, {"recording_ref": ""}),
        (CallCompleted, EventType.CALL_COMPLETED, {"end_reason": "exploded"}),
        (CallCompleted, EventType.CALL_COMPLETED, {"run_item_id": None}),  # simulation needs it
        (EvaluationCompleted, EventType.EVALUATION_COMPLETED, {"overall_score": 101}),
        (EvaluationCompleted, EventType.EVALUATION_COMPLETED, {"passed": None}),
        (RunCompleted, EventType.RUN_COMPLETED, {"status": "queued"}),
        (ProgressEvent, EventType.PROGRESS, {"kind": "bogus"}),
        (ProgressEvent, EventType.PROGRESS, {"overall_score": None}),
        (ScenarioGenerateRequested, EventType.SCENARIO_GENERATE_REQUESTED, {"count": 0}),
        (DialectClipRequested, EventType.DIALECT_CLIP_REQUESTED, {"engines": []}),
        (DialectClipRequested, EventType.DIALECT_CLIP_REQUESTED, {"expected_results": 0}),
    ],
)
def test_invalid_values_are_rejected(
    model: type[Any], base: EventType, change: dict[str, Any]
) -> None:
    data, _ = SAMPLES[base]
    model.model_validate(data)  # the unmodified sample is valid
    with pytest.raises(ValidationError):
        model.model_validate({**data, **change})


def test_progress_needs_run_or_call_id() -> None:
    with pytest.raises(ValidationError):
        ProgressEvent(kind="run.completed")


def test_envelope_rules() -> None:
    data, _ = SAMPLES[EventType.CALL_COMPLETED]
    payload = CallCompleted.model_validate(data)
    good = make_envelope(payload, producer="p", correlation_id="c")
    base = good.model_dump(mode="json")

    with pytest.raises(ValidationError):  # naive timestamp
        parse_envelope({**base, "occurred_at": "2026-10-26T10:15:00"})
    with pytest.raises(ValidationError):  # attempt beyond 3 + DLQ copy
        parse_envelope({**base, "attempt": 5})
    with pytest.raises(ValidationError):  # missing producer
        parse_envelope({k: v for k, v in base.items() if k != "producer"})
    with pytest.raises(ValidationError):  # extra envelope field
        parse_envelope({**base, "extra": True})
    with pytest.raises(ValidationError):  # payload of another event type
        parse_envelope({**base, "type": "run.completed"})
    with pytest.raises(UnknownEventTypeError):
        parse_envelope({**base, "type": "call.exploded"})


def test_naive_datetime_in_make_envelope_is_rejected() -> None:
    payload = CallCompleted(call_id=CALL, source="upload")
    with pytest.raises(ValidationError):
        make_envelope(
            payload, producer="p", correlation_id="c", occurred_at=datetime(2026, 10, 26, 10, 0)
        )
    aware = make_envelope(
        payload, producer="p", correlation_id="c", occurred_at=datetime(2026, 10, 26, tzinfo=UTC)
    )
    assert aware.occurred_at.tzinfo is not None


def test_deterministic_event_id() -> None:
    first = deterministic_event_id(RUN, EventType.CALL_COMPLETED)
    assert first == deterministic_event_id(RUN, "call.completed")
    assert first == uuid.uuid5(RUN, "call.completed")
    assert first != deterministic_event_id(RUN, EventType.EVALUATION_COMPLETED)
    assert first != deterministic_event_id(ITEM, EventType.CALL_COMPLETED)
    with pytest.raises(ValueError):
        deterministic_event_id(RUN, "not.an.event")


def test_event_json_schemas_cover_every_event() -> None:
    schemas = event_json_schemas()
    assert set(schemas["events"]) == {t.value for t in EventType}
    assert "payload" in schemas["envelope"]["properties"]
    for event_type, entry in schemas["events"].items():
        assert entry["topic"] == EVENT_TOPIC[EventType(event_type)].value
        assert entry["payload_schema"]["type"] == "object"
        json.dumps(entry)  # serialisable
    assert schemas["events"]["call.requested"]["key"] == "run_item_id"
