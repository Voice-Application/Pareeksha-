"""Persona and noise-profile schemas accept and reject the right inputs; cursor round trip."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pareeksha.api.crud import decode_cursor, encode_cursor
from pareeksha.api.errors import ApiError
from pareeksha.schemas.personas import (
    NoiseProfileCreate,
    NoiseProfileUpdate,
    PersonaCreate,
    PersonaUpdate,
)

PERSONA = {"name": "Manju", "language": "kn-IN", "voice_id": "Prakash"}


def test_persona_defaults_and_full_form() -> None:
    p = PersonaCreate.model_validate(PERSONA)
    assert p.speed == 1.0 and p.patience_turns == 8 and p.silence_habit == "normal"
    full = PersonaCreate.model_validate(
        {**PERSONA, "speed": 2.0, "interruption_level": 3, "emotion": "angry"}
    )
    assert full.speed == 2.0 and full.interruption_level == 3


@pytest.mark.parametrize(
    "bad",
    [
        {"speed": 0.4},
        {"speed": 2.1},
        {"patience_turns": 0},
        {"interruption_level": 4},
        {"emotion": "ecstatic"},
        {"silence_habit": "never"},
        {"code_mix_style": "extreme"},
        {"voice_id": ""},
        {"language": "k"},
        {"unknown_field": 1},
    ],
)
def test_persona_rejects(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        PersonaCreate.model_validate({**PERSONA, **bad})
    with pytest.raises(ValidationError):
        PersonaUpdate.model_validate(bad)


def test_noise_profile_requires_snr_with_a_background() -> None:
    ok = NoiseProfileCreate(name="n", background_category="market_crowd", snr_db=5)
    assert ok.codec == "none" and ok.sample_rate == 16000
    NoiseProfileCreate(name="clean")
    with pytest.raises(ValidationError, match="snr_db is required"):
        NoiseProfileCreate(name="n", background_category="market_crowd")


@pytest.mark.parametrize(
    "bad",
    [
        {"sample_rate": 44100},
        {"codec": "opus"},
        {"packet_loss_pct": 25},
        {"packet_loss_pct": -1},
        {"snr_db": 100},
        {"name": ""},
    ],
)
def test_noise_profile_rejects(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        NoiseProfileCreate.model_validate({"name": "n", **bad})
    with pytest.raises(ValidationError):
        NoiseProfileUpdate.model_validate(bad)


def test_cursor_round_trip_and_garbage() -> None:
    now, row_id = datetime.now(UTC), uuid4()
    assert decode_cursor(encode_cursor(now, row_id)) == (now, row_id)
    for garbage in ("", "!!!", "e30", "bm90LWpzb24"):
        with pytest.raises(ApiError) as caught:
            decode_cursor(garbage)
        assert caught.value.status_code == 400
