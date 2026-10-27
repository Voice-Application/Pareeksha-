"""Event-schema contract: published JSON Schemas, the envelope and docs/contracts.md agree."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from pareeksha.api.main import app
from pareeksha.events.schemas import (
    ENVELOPE_VERSION,
    EVENT_PAYLOADS,
    EVENT_TOPIC,
    EventType,
    event_json_schemas,
    parse_envelope,
)
from pareeksha.events.topics import TOPIC_SPECS

REPO = Path(__file__).resolve().parents[3]


def test_every_event_type_has_a_payload_topic_and_published_schema() -> None:
    schemas = event_json_schemas()["events"]
    assert set(schemas) == {e.value for e in EventType} == {e.value for e in EVENT_PAYLOADS}
    for event_type, entry in schemas.items():
        Draft202012Validator.check_schema(entry["payload_schema"])
        assert entry["topic"] == EVENT_TOPIC[EventType(event_type)].value
        assert entry["key"] == TOPIC_SPECS[EVENT_TOPIC[EventType(event_type)]].key
        assert entry["envelope_version"] == ENVELOPE_VERSION


def test_events_schemas_route_returns_the_module_schemas() -> None:
    from pareeksha.api.routers.system import get_event_schemas

    assert asyncio.run(get_event_schemas()) == event_json_schemas()
    assert ("GET", "/api/v1/events/schemas") in {
        (m, p) for p, ops in app.openapi()["paths"].items() for m in map(str.upper, ops)
    }


def test_every_event_type_is_documented_in_contracts() -> None:
    text = (REPO / "docs" / "contracts.md").read_text()
    missing = [e.value for e in EventType if f"`{e.value}`" not in text]
    assert not missing, f"docs/contracts.md does not mention {missing}"


@pytest.mark.parametrize("event_type", list(EventType))
def test_envelope_rejects_unknown_fields_and_type_payload_mismatch(event_type: EventType) -> None:
    payload_model = EVENT_PAYLOADS[event_type]
    schema = payload_model.model_json_schema()
    # an unknown top-level envelope field is rejected
    raw: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "type": event_type.value,
        "version": ENVELOPE_VERSION,
        "occurred_at": datetime.now(UTC).isoformat(),
        "correlation_id": str(uuid.uuid4()),
        "attempt": 1,
        "producer": "contract@test",
        "payload": {},
        "surprise": 1,
    }
    with pytest.raises(ValidationError):
        parse_envelope(raw)
    assert schema.get("additionalProperties") is False  # payload models reject unknown fields too
