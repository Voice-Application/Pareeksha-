"""Text-to-speech access for the API (persona preview), overridable in tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

#: One short line per language for ``POST /personas/{id}/preview``; other languages use English.
SAMPLE_LINES: dict[str, str] = {
    "kn-IN": "ನಮಸ್ಕಾರ, ನನ್ನ ಇಎಂಐ ಬಗ್ಗೆ ಒಂದು ಪ್ರಶ್ನೆ ಇತ್ತು.",
    "hi-IN": "नमस्ते, मुझे अपनी ईएमआई के बारे में एक सवाल पूछना था।",
    "en-IN": "Hello, I had a question about my EMI payment.",
}
_FALLBACK_LINE = SAMPLE_LINES["en-IN"]


def sample_line(language: str) -> str:
    return SAMPLE_LINES.get(language, _FALLBACK_LINE)


class Synthesizer(Protocol):
    """What the preview route needs: synthesise ``text`` and return WAV bytes."""

    def synthesize_wav(
        self, text: str, voice: str, language: str, *, speed: float, model: str
    ) -> bytes: ...


class GnaniSynthesizer:
    """Gnani Timbre TTS through ``pareeksha.gnani.GnaniSpeech`` (cached on disk)."""

    def __init__(self, api_key: str | None, cache_dir: Path | None) -> None:
        self._api_key = api_key
        self._cache_dir = cache_dir

    def synthesize_wav(
        self, text: str, voice: str, language: str, *, speed: float, model: str
    ) -> bytes:
        if not self._api_key:
            raise RuntimeError("GNANI_API_KEY is not configured on the server")
        from pareeksha.gnani import GnaniSpeech  # lazy: the SDK is only needed for previews

        speech = GnaniSpeech(self._api_key, cache_dir=self._cache_dir)
        return speech.synthesize(text, voice, language, speed=speed, model=model).audio


def get_synthesizer() -> Synthesizer:
    """FastAPI dependency; a missing ``GNANI_API_KEY`` surfaces as 502 when a preview is made."""
    api_key = os.environ.get("GNANI_API_KEY")
    data_dir = os.environ.get("DATA_DIR")
    return GnaniSynthesizer(api_key, Path(data_dir) / "tts_cache" if data_dir else None)
