"""Provider registry / factory and availability status.

``get_stt_provider()`` / ``get_tts_provider()`` build the provider named by ``STT_PROVIDER`` /
``TTS_PROVIDER`` (default ``gnani``); pass ``name=`` or a :class:`SpeechSelection` to override per
agent or per run. Adapters are imported on demand so that an unused vendor's dependencies are never
loaded.
"""

from __future__ import annotations

import importlib
from typing import Any

from pydantic import BaseModel

from pareeksha.speech.base import (
    SpeechProviderName,
    SpeechSelection,
    STTCapabilities,
    STTProvider,
    TTSCapabilities,
    TTSProvider,
)
from pareeksha.speech.config import SpeechSettings

# provider -> (module, STT class, TTS class)
_ADAPTERS: dict[SpeechProviderName, tuple[str, str, str]] = {
    SpeechProviderName.GNANI: ("gnani", "GnaniSTT", "GnaniTTS"),
    SpeechProviderName.GOOGLE: ("google", "GoogleSTT", "GoogleTTS"),
    SpeechProviderName.AZURE: ("azure", "AzureSTT", "AzureTTS"),
    SpeechProviderName.ELEVENLABS: ("elevenlabs", "ElevenLabsSTT", "ElevenLabsTTS"),
    SpeechProviderName.DEEPGRAM: ("deepgram", "DeepgramSTT", "DeepgramTTS"),
}


def _adapter_class(name: SpeechProviderName, index: int) -> Any:
    entry = _ADAPTERS[name]
    module = importlib.import_module(f"pareeksha.speech.providers.{entry[0]}")
    return getattr(module, entry[index])


def get_stt_provider(
    name: SpeechProviderName | str | None = None,
    *,
    selection: SpeechSelection | None = None,
    settings: SpeechSettings | None = None,
    **kwargs: Any,
) -> STTProvider:
    """Order of precedence: ``name`` argument, ``selection.stt``, ``STT_PROVIDER`` env."""
    s = settings or SpeechSettings()
    chosen = SpeechProviderName(name) if name else (selection.stt if selection else None)
    cls = _adapter_class(chosen or s.stt_provider, 1)
    provider: STTProvider = cls(s, **kwargs)
    return provider


def get_tts_provider(
    name: SpeechProviderName | str | None = None,
    *,
    selection: SpeechSelection | None = None,
    settings: SpeechSettings | None = None,
    **kwargs: Any,
) -> TTSProvider:
    """Order of precedence: ``name`` argument, ``selection.tts``, ``TTS_PROVIDER`` env."""
    s = settings or SpeechSettings()
    chosen = SpeechProviderName(name) if name else (selection.tts if selection else None)
    cls = _adapter_class(chosen or s.tts_provider, 2)
    provider: TTSProvider = cls(s, **kwargs)
    return provider


class ProviderStatus(BaseModel):
    """One row of ``GET /api/v1/speech/providers``. Never contains key material."""

    name: SpeechProviderName
    #: All required env vars are present. This does not prove the credentials are valid.
    configured: bool
    missing_env: list[str]
    stt_default: bool
    tts_default: bool
    stt: STTCapabilities
    tts: TTSCapabilities


def provider_status(settings: SpeechSettings | None = None) -> list[ProviderStatus]:
    s = settings or SpeechSettings()
    rows: list[ProviderStatus] = []
    for name in _ADAPTERS:
        missing = s.missing_env(name)
        rows.append(
            ProviderStatus(
                name=name,
                configured=not missing,
                missing_env=missing,
                stt_default=name is s.stt_provider,
                tts_default=name is s.tts_provider,
                stt=_adapter_class(name, 1).capabilities,
                tts=_adapter_class(name, 2).capabilities,
            )
        )
    return rows
