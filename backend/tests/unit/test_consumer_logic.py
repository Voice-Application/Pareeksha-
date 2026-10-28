"""Pure-logic tests for the consumer framework (no broker or database needed)."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pydantic
import pytest

from pareeksha.events.consumer import (
    REGISTRY,
    Ctx,
    Disposition,
    Outgoing,
    PermanentError,
    RetryableError,
    RetryPolicy,
    classify,
    consumer,
)
from pareeksha.events.runtime import (
    HEADER_CONSUMER_GROUP,
    JsonFormatter,
    decode_headers,
    encode_headers,
    parse_utc,
    utc_iso,
)
from pareeksha.events.schemas import UnknownEventTypeError
from pareeksha.events.settings import EventSettings, libpq_url
from pareeksha.events.topics import HEADER_ERROR, HEADER_TARGET_TOPIC, Topics
from pareeksha.workers.dlq_recorder import to_dead_letter


class _HttpError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status_code = status


class _Response:
    def __init__(self, status: int) -> None:
        self.status_code = status


class _ClientError(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.response = _Response(status)


class _Model(pydantic.BaseModel):
    n: int


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RetryableError("x"), Disposition.RETRY),
        (PermanentError("x"), Disposition.PERMANENT),
        (TimeoutError(), Disposition.RETRY),
        (ConnectionResetError(), Disposition.RETRY),
        (psycopg.OperationalError("db gone"), Disposition.RETRY),
        (_HttpError(503), Disposition.RETRY),
        (_HttpError(429), Disposition.RETRY),
        (_HttpError(408), Disposition.RETRY),
        (_HttpError(400), Disposition.PERMANENT),
        (_HttpError(404), Disposition.PERMANENT),
        (_ClientError(502), Disposition.RETRY),
        (_ClientError(422), Disposition.PERMANENT),
        (ValueError("bad"), Disposition.PERMANENT),
        (KeyError("k"), Disposition.PERMANENT),
        (TypeError("t"), Disposition.PERMANENT),
        (UnknownEventTypeError("nope"), Disposition.PERMANENT),
        (psycopg.errors.DataError("too long"), Disposition.PERMANENT),
        (RuntimeError("unknown failure"), Disposition.RETRY),
    ],
)
def test_classify(exc: BaseException, expected: Disposition) -> None:
    assert classify(exc) is expected


def test_classify_pydantic_validation_error_is_permanent() -> None:
    with pytest.raises(pydantic.ValidationError) as info:
        _Model.model_validate({"n": "not a number"})
    assert classify(info.value) is Disposition.PERMANENT


def test_retry_policy_defaults_follow_the_contract() -> None:
    policy = RetryPolicy()
    assert (policy.delay(2), policy.delay(3), policy.throttle_delay_seconds) == (30, 300, 30)


def test_consumer_decorator_registers_spec_and_returns_handler() -> None:
    async def handle(env: Any, ctx: Ctx) -> list[Outgoing]:
        return []

    decorated = consumer(group="unit-registry", topic=Topics.CALL_COMPLETED)(handle)
    spec = REGISTRY["unit-registry"]
    assert decorated is handle
    assert spec.handler is handle and spec.topics == (Topics.CALL_COMPLETED,)
    assert spec.auto_offset_reset == "earliest" and spec.reproduce is None
    multi = consumer(group="unit-registry-2", topic=[Topics.RETRY_30S, Topics.RETRY_5M])(handle)
    assert multi is handle and REGISTRY["unit-registry-2"].topics == (
        Topics.RETRY_30S,
        Topics.RETRY_5M,
    )


def test_dead_letter_from_valid_envelope_message() -> None:
    event_id = uuid.uuid4()
    value = json.dumps(
        {"event_id": str(event_id), "attempt": 3, "type": "audit.requested"}
    ).encode()
    dl = to_dead_letter(
        value,
        b"call-1",
        {
            HEADER_TARGET_TOPIC: Topics.AUDIT_REQUESTED.value,
            HEADER_CONSUMER_GROUP: "auditor",
            HEADER_ERROR: "boom",
        },
        Topics.DLQ.value,
    )
    assert (dl.event_id, dl.key, dl.consumer_group, dl.error, dl.attempts) == (
        event_id,
        "call-1",
        "auditor",
        "boom",
        3,
    )
    assert dl.original_topic == Topics.AUDIT_REQUESTED.value


def test_dead_letter_from_garbage_is_still_recorded_with_a_stable_id() -> None:
    first = to_dead_letter(b"\xff not json", None, {}, Topics.DLQ.value)
    second = to_dead_letter(b"\xff not json", None, {}, Topics.DLQ.value)
    assert first.event_id == second.event_id
    assert first.envelope["raw"].endswith("not json")
    assert (first.original_topic, first.key, first.consumer_group, first.attempts) == (
        Topics.DLQ.value,
        "",
        "unknown",
        1,
    )
    assert to_dead_letter(None, None, {}, "t").envelope == {"raw": ""}
    assert to_dead_letter(b"[1, 2]", None, {}, "t").envelope == {"raw": [1, 2]}


def test_header_round_trip_and_timestamps() -> None:
    headers = {"x-a": "ä", "x-b": "2"}
    assert decode_headers(encode_headers(headers)) == headers
    assert decode_headers(None) == {}
    now = datetime(2026, 10, 24, 10, 0, 0, 123000, tzinfo=UTC)
    assert utc_iso(now) == "2026-10-24T10:00:00.123000Z"
    assert parse_utc(utc_iso(now)) == now
    assert parse_utc("2026-10-24T10:00:00") == datetime(2026, 10, 24, 10, tzinfo=UTC)
    assert parse_utc("garbage") is None
    assert parse_utc(utc_iso(now + timedelta(minutes=5))) - now == timedelta(minutes=5)  # type: ignore[operator]


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    settings = EventSettings.from_env()
    assert settings.bootstrap_servers == "kafka:9092"
    assert settings.database_url == "postgresql://u:p@db:5432/x"
    assert libpq_url("postgresql://already/plain") == "postgresql://already/plain"


def test_json_log_formatter_includes_event_fields() -> None:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "processed %s", ("x",), None)
    record.group = "evaluator"
    record.event_id = "abc"
    line = json.loads(JsonFormatter().format(record))
    assert (
        line["msg"] == "processed x" and line["group"] == "evaluator" and line["event_id"] == "abc"
    )
    try:
        raise RuntimeError("bad")
    except RuntimeError:
        import sys

        rec = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    assert "RuntimeError: bad" in json.loads(JsonFormatter().format(rec))["exc"]
