"""Speech provider selection and settings, read from the environment (see .env.example).

``STT_PROVIDER`` / ``TTS_PROVIDER`` default to ``gnani``. Cost rates are in the owner's currency
units: Gnani keeps the generic ``COST_TTS_PER_1K_CHARS`` / ``COST_STT_*_PER_MIN`` names from
VOICE-01, the other vendors use ``COST_<VENDOR>_TTS_PER_1K_CHARS`` / ``COST_<VENDOR>_STT_PER_MIN``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from pareeksha.speech.base import SpeechProviderName


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True, case_sensitive=False
    )

    stt_provider: SpeechProviderName = SpeechProviderName.GNANI
    tts_provider: SpeechProviderName = SpeechProviderName.GNANI

    # Gnani (cost names predate this module, see proof/VOICE-01)
    gnani_api_key: str | None = Field(default=None, repr=False)
    gnani_tts_model: str = "timbre-v3.0"
    gnani_tts_voice: str | None = None
    cost_tts_per_1k_chars: float | None = Field(default=None, ge=0)
    cost_stt_rest_per_min: float | None = Field(default=None, ge=0)
    cost_stt_stream_per_min: float | None = Field(default=None, ge=0)
    cost_stt_batch_per_min: float | None = Field(default=None, ge=0)

    # Google Cloud: Speech-to-Text v2 + Text-to-Speech, service-account JSON as one env value
    google_application_credentials_json: str | None = Field(default=None, repr=False)
    #: Chirp models are regional; "global" works for the older models (long, short).
    google_speech_location: str = "us-central1"
    google_stt_model: str = "chirp_2"
    google_tts_voice: str | None = None
    cost_google_tts_per_1k_chars: float | None = Field(default=None, ge=0)
    cost_google_stt_per_min: float | None = Field(default=None, ge=0)

    # Azure AI Speech
    azure_speech_key: str | None = Field(default=None, repr=False)
    azure_speech_region: str | None = None
    azure_tts_voice: str | None = None
    cost_azure_tts_per_1k_chars: float | None = Field(default=None, ge=0)
    cost_azure_stt_per_min: float | None = Field(default=None, ge=0)

    # ElevenLabs
    elevenlabs_api_key: str | None = Field(default=None, repr=False)
    elevenlabs_stt_model: str = "scribe_v1"
    elevenlabs_tts_model: str = "eleven_multilingual_v2"
    elevenlabs_tts_voice: str | None = None
    cost_elevenlabs_tts_per_1k_chars: float | None = Field(default=None, ge=0)
    cost_elevenlabs_stt_per_min: float | None = Field(default=None, ge=0)

    # Deepgram
    deepgram_api_key: str | None = Field(default=None, repr=False)
    deepgram_stt_model: str = "nova-3"
    deepgram_tts_model: str = "aura-2-thalia-en"
    cost_deepgram_tts_per_1k_chars: float | None = Field(default=None, ge=0)
    cost_deepgram_stt_per_min: float | None = Field(default=None, ge=0)

    def stt_rate_per_min(
        self, provider: SpeechProviderName, operation: str = "stt_batch"
    ) -> float | None:
        if provider is SpeechProviderName.GNANI:
            return {
                "stt_rest": self.cost_stt_rest_per_min,
                "stt_stream": self.cost_stt_stream_per_min,
            }.get(operation, self.cost_stt_batch_per_min)
        return getattr(self, f"cost_{provider.value}_stt_per_min")  # type: ignore[no-any-return]

    def tts_rate_per_1k_chars(self, provider: SpeechProviderName) -> float | None:
        if provider is SpeechProviderName.GNANI:
            return self.cost_tts_per_1k_chars
        return getattr(self, f"cost_{provider.value}_tts_per_1k_chars")  # type: ignore[no-any-return]

    def stt_cost(
        self, provider: SpeechProviderName, audio_seconds: float, operation: str = "stt_batch"
    ) -> float | None:
        rate = self.stt_rate_per_min(provider, operation)
        return None if rate is None else audio_seconds / 60 * rate

    def tts_cost(self, provider: SpeechProviderName, characters: int) -> float | None:
        rate = self.tts_rate_per_1k_chars(provider)
        return None if rate is None else characters / 1000 * rate

    def missing_env(self, provider: SpeechProviderName) -> list[str]:
        """Names of required env vars that are not set (empty = configured)."""
        required: dict[SpeechProviderName, dict[str, object]] = {
            SpeechProviderName.GNANI: {"GNANI_API_KEY": self.gnani_api_key},
            SpeechProviderName.GOOGLE: {
                "GOOGLE_APPLICATION_CREDENTIALS_JSON": self.google_application_credentials_json
            },
            SpeechProviderName.AZURE: {
                "AZURE_SPEECH_KEY": self.azure_speech_key,
                "AZURE_SPEECH_REGION": self.azure_speech_region,
            },
            SpeechProviderName.ELEVENLABS: {"ELEVENLABS_API_KEY": self.elevenlabs_api_key},
            SpeechProviderName.DEEPGRAM: {"DEEPGRAM_API_KEY": self.deepgram_api_key},
        }
        return [name for name, value in required[provider].items() if not value]
