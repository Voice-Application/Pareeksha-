"""Shared helpers for the speech provider tests. All vendor HTTP is mocked with respx."""

from __future__ import annotations

import pytest

from pareeksha.speech.config import SpeechSettings
from pareeksha.speech.wav import pcm_to_wav

ENV_PREFIXES = (
    "STT_",
    "TTS_",
    "GNANI_",
    "GOOGLE_",
    "AZURE_",
    "ELEVENLABS_",
    "DEEPGRAM_",
    "COST_",
)


@pytest.fixture(autouse=True)
def clean_speech_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    for name in list(os.environ):
        if name.upper().startswith(ENV_PREFIXES):
            monkeypatch.delenv(name)


def make_settings(**kwargs: object) -> SpeechSettings:
    return SpeechSettings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def make_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    return pcm_to_wav(b"\x01\x00" * int(seconds * rate), rate)
