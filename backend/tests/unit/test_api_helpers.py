"""Small API helpers: constraint-error mapping and the Gnani synthesizer wrapper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

import pareeksha.gnani
from pareeksha.api.crud import constraint_error
from pareeksha.api.speech import GnaniSynthesizer, sample_line


class _Orig(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__("db error")
        self.sqlstate = sqlstate


def _integrity(sqlstate: str | None) -> IntegrityError:
    return IntegrityError("stmt", {}, _Orig(sqlstate))


@pytest.mark.parametrize(("state", "status"), [("23505", 409), ("23503", 409), ("23514", 400)])
def test_known_constraint_violations_map_to_api_errors(state: str, status: int) -> None:
    error = constraint_error(_integrity(state), "in use")
    assert error.status_code == status
    if status == 409:
        assert error.code == "conflict" and error.message == "in use"


@pytest.mark.parametrize("state", ["23502", None])
def test_unexpected_integrity_errors_are_not_swallowed(state: str | None) -> None:
    exc = _integrity(state)
    with pytest.raises(IntegrityError) as caught:
        constraint_error(exc, "in use")
    assert caught.value is exc


def test_sample_line_falls_back_to_english() -> None:
    assert sample_line("ta-IN") == sample_line("en-IN")
    assert sample_line("kn-IN") != sample_line("en-IN")


def test_gnani_synthesizer_passes_voice_speed_model_and_cache_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    class FakeSpeech:
        def __init__(self, api_key: str, cache_dir: Path | None = None) -> None:
            seen["init"] = (api_key, cache_dir)

        def synthesize(self, text: str, voice: str, language: str, **kwargs: Any) -> Any:
            seen["call"] = (text, voice, language, kwargs)
            return type("Result", (), {"audio": b"WAVDATA"})()

    monkeypatch.setattr(pareeksha.gnani, "GnaniSpeech", FakeSpeech)
    audio = GnaniSynthesizer("key", tmp_path).synthesize_wav(
        "hello", "Prakash", "kn-IN", speed=1.1, model="timbre-v3.0"
    )
    assert audio == b"WAVDATA"
    assert seen["init"] == ("key", tmp_path)
    assert seen["call"] == ("hello", "Prakash", "kn-IN", {"speed": 1.1, "model": "timbre-v3.0"})


def test_gnani_synthesizer_without_a_key_raises() -> None:
    with pytest.raises(RuntimeError, match="GNANI_API_KEY"):
        GnaniSynthesizer(None, None).synthesize_wav("x", "v", "en-IN", speed=1.0, model="m")
