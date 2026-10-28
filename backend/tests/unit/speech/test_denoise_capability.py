"""EVAL-04: `denoise` is a declared capability; providers without it refuse, never ignore."""

from __future__ import annotations

import pytest

from pareeksha.speech.base import STTProvider, UnsupportedCapabilityError
from pareeksha.speech.providers.azure import AzureSTT
from pareeksha.speech.providers.deepgram import DeepgramSTT
from pareeksha.speech.providers.elevenlabs import ElevenLabsSTT
from pareeksha.speech.providers.gnani import GnaniSTT
from pareeksha.speech.providers.google import GoogleSTT

from .conftest import make_settings, make_wav

SETTINGS = make_settings(
    azure_speech_key="k",
    azure_speech_region="r",
    deepgram_api_key="k",
    elevenlabs_api_key="k",
    google_application_credentials_json="{}",
)


def test_only_gnani_declares_denoise() -> None:
    assert GnaniSTT.capabilities.denoise is True
    for cls in (AzureSTT, DeepgramSTT, ElevenLabsSTT, GoogleSTT):
        assert cls.capabilities.denoise is False


@pytest.mark.parametrize("cls", [AzureSTT, DeepgramSTT, ElevenLabsSTT])
async def test_providers_without_denoise_refuse(cls: type[STTProvider]) -> None:
    stt = cls(SETTINGS)  # type: ignore[call-arg]
    with pytest.raises(UnsupportedCapabilityError, match="denoise"):
        await stt.transcribe(make_wav(), "en-IN", denoise=True)
    await stt.aclose()
