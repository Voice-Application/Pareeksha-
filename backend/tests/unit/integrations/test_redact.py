"""Secret masking for dead letters and delivery logs."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from pareeksha.api.routers.integrations import _delivery_out
from pareeksha.events.topics import HEADER_ERROR, HEADER_TARGET_TOPIC
from pareeksha.integrations.redact import MASK, redact_json, redact_text
from pareeksha.ops.dlq import _out
from pareeksha.workers.dlq_recorder import to_dead_letter

SECRET = "hunter2-very-secret-value"


@pytest.mark.parametrize(
    "text",
    [
        f"Authorization: Bearer {SECRET}",
        f"header authorization={SECRET}",
        f"failed with Bearer {SECRET}",
        f"key {SECRET}".replace(f"key {SECRET}", f"pk_live_{SECRET.replace('-', '')}"),
        f"POST https://hooks.example.com/in?token={SECRET}&x=1 failed",
        f"GET https://x.example.com/?a=1&api_key={SECRET}",
        f"https://user:{SECRET}@host.example.com/path",
        f'{{"signing_secret": "{SECRET}"}}',
        f"{{'api_key': '{SECRET}', 'url': 'x'}}",
        f"password={SECRET}",
        f"client_secret: {SECRET}",
    ],
)
def test_text_secrets_are_masked(text: str) -> None:
    out = redact_text(text)
    assert SECRET.replace("-", "") not in out.replace("-", "")
    assert MASK in out


def test_innocent_text_is_unchanged() -> None:
    text = "ConnectionError: could not reach https://hooks.example.com/in?page=2 (HTTP 502)"
    assert redact_text(text) == text


def test_pydantic_validation_errors_do_not_echo_input() -> None:
    class Config(BaseModel):
        url: int

    with pytest.raises(ValidationError) as caught:
        Config.model_validate({"url": SECRET, "api_key": SECRET})
    assert SECRET in str(caught.value)  # the premise: pydantic prints the input
    out = redact_text(f"ValidationError: {caught.value}")
    assert SECRET not in out
    assert "input_value=" in out and "int_parsing" in out  # the useful part stays


def test_pydantic_errors_dict_input_is_masked() -> None:
    errors = [{"loc": ("url",), "msg": "bad", "input": SECRET}]
    assert SECRET not in redact_text(str(errors))


def test_json_masks_sensitive_keys_and_nested_strings() -> None:
    value: dict[str, Any] = {
        "payload": {
            "call_id": "c1",
            "signing_secret": SECRET,
            "headers": [{"Authorization": f"Bearer {SECRET}"}],
            "tokens_used": 12,
            "note": f"see https://x.example.com/?token={SECRET}",
        }
    }
    out = redact_json(value)
    assert SECRET not in json.dumps(out)
    assert out["payload"]["call_id"] == "c1" and out["payload"]["tokens_used"] == 12
    assert value["payload"]["signing_secret"] == SECRET  # the input is not modified


def test_recorder_stores_a_redacted_error_and_keeps_the_envelope() -> None:
    envelope = {"event_id": str(uuid.uuid4()), "payload": {"api_key": SECRET}, "attempt": 3}
    dl = to_dead_letter(
        json.dumps(envelope).encode(),
        b"k",
        {
            HEADER_ERROR: f"ValueError: bad https://x.example.com/?token={SECRET}",
            HEADER_TARGET_TOPIC: "t",
        },
        "dlq.v1",
    )
    assert SECRET not in dl.error
    assert dl.envelope["payload"]["api_key"] == SECRET  # replay needs the original


def test_recorder_redacts_an_unparseable_message() -> None:
    dl = to_dead_letter(f"not json Authorization: Bearer {SECRET}".encode(), None, {}, "dlq.v1")
    assert SECRET not in json.dumps(dl.envelope)


def test_dlq_api_output_is_redacted() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        original_topic="t",
        consumer_group="g",
        error=f"Boom api_key={SECRET}",
        attempts=1,
        status="open",
        failed_at=datetime.now(UTC),
        envelope={"payload": {"password": SECRET, "id": 1}},
    )
    out = _out(row)  # type: ignore[arg-type]
    assert SECRET not in out.model_dump_json()
    assert out.envelope["payload"]["id"] == 1


def test_delivery_log_excerpt_is_redacted() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        direction="outbound",
        status="failed",
        http_status=401,
        external_id=None,
        attempts=1,
        response_excerpt=f'{{"error":"bad","token": "{SECRET}"}} at https://a.example/?api_key={SECRET}',
        created_at=datetime.now(UTC),
    )
    assert SECRET not in _delivery_out(row).model_dump_json()  # type: ignore[arg-type]
