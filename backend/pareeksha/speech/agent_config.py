"""Per-agent speech provider override, stored in ``agents.adapter_config["speech"]`` (EVAL-04b).

``{"speech": {"stt": "gnani", "tts": "elevenlabs"}}`` makes the platform use those providers for
that agent instead of the ``STT_PROVIDER`` / ``TTS_PROVIDER`` environment defaults. Either key may
be omitted. The agent schema has no dedicated field, so the free-form ``adapter_config`` carries it
(additive; docs/contracts.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from pareeksha.speech.base import SpeechConfigError, SpeechSelection

SPEECH_KEY = "speech"


def speech_selection(adapter_config: Mapping[str, Any] | None) -> SpeechSelection | None:
    """The agent's override, or ``None`` if it has none. ``SpeechConfigError`` if invalid."""
    raw = (adapter_config or {}).get(SPEECH_KEY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise SpeechConfigError(
            f"adapter_config.{SPEECH_KEY} must be an object like {{'stt': ...}}"
        )
    try:
        selection = SpeechSelection.model_validate(dict(raw))
    except ValidationError as exc:
        raise SpeechConfigError(
            f"adapter_config.{SPEECH_KEY} is invalid: {exc.errors()[0]['msg']}"
        ) from exc
    return selection if (selection.stt or selection.tts) else None
