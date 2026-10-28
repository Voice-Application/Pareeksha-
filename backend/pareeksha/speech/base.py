"""Speech provider interfaces (STT and TTS).

Contract change owner-approved 2026-10-24, see CHANGELOG.md.

Same pattern as ``pareeksha.llm.base``: abstract provider classes, plain pydantic value types,
provider-independent errors. Providers (gnani default, google, azure, elevenlabs, deepgram) live in
``pareeksha.speech.providers``; ``pareeksha.speech.registry`` picks them from ``STT_PROVIDER`` /
``TTS_PROVIDER`` or from a per-agent / per-run :class:`SpeechSelection`.

Conventions every provider follows:
- ``language`` is a BCP-47 tag as used elsewhere in Pareeksha (``kn-IN``, ``hi-IN``, ``en-IN``).
- Batch STT input is a WAV container; streaming STT input is raw 16-bit mono little-endian PCM.
- TTS output is always a WAV container (linear PCM, 16-bit, mono) at ``sample_rate``, which the
  provider states in the result; ``TTSCapabilities.sample_rates`` lists what it can produce.
- Optional features are declared in the capability metadata and raise
  :class:`UnsupportedCapabilityError` when requested but not offered (never silently ignored).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class SpeechProviderName(StrEnum):
    GNANI = "gnani"
    GOOGLE = "google"
    AZURE = "azure"
    ELEVENLABS = "elevenlabs"
    DEEPGRAM = "deepgram"


class SpeechError(Exception):
    """Base class for speech provider failures."""


class SpeechRetryableError(SpeechError):
    """Timeouts, connection errors, 5xx and 429 after the provider's own retries."""

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class SpeechPermanentError(SpeechError):
    """Bad credentials, other 4xx, unsupported language / voice / audio. Not retried."""


class SpeechConfigError(SpeechError, ValueError):
    """The selected provider is not configured (missing key or region)."""


class UnsupportedCapabilityError(SpeechError):
    """The provider does not offer the requested feature (see its capability metadata)."""


class SpeechUsage(BaseModel):
    """One billable provider call, for ``api_usage`` and cost estimates."""

    provider: SpeechProviderName
    operation: str = Field(examples=["tts", "stt_batch", "stt_stream"])
    audio_seconds: float = Field(default=0.0, ge=0)
    characters: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    #: In the units of the ``COST_*`` rates; ``None`` when the rates are not configured.
    est_cost: float | None = None


class WordTiming(BaseModel):
    text: str
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    #: 0..1, ``None`` where the provider does not report it.
    confidence: float | None = Field(default=None, ge=0, le=1)
    speaker: str | None = None


class TranscriptSegment(BaseModel):
    text: str
    start_s: float = Field(ge=0)
    end_s: float = Field(ge=0)
    speaker: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class Transcript(BaseModel):
    provider: SpeechProviderName
    model: str | None = None
    text: str
    #: Language the provider reports or, failing that, the one requested.
    language: str
    duration_s: float = Field(ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    segments: list[TranscriptSegment] = Field(default_factory=list)
    words: list[WordTiming] = Field(default_factory=list)
    usage: SpeechUsage


class StreamingTranscript(BaseModel):
    """An interim (``is_final=False``) or final result from a live stream."""

    text: str
    is_final: bool
    confidence: float | None = Field(default=None, ge=0, le=1)
    start_s: float | None = None
    end_s: float | None = None


class STTCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    streaming: bool
    batch: bool = True
    word_timings: bool
    word_confidence: bool
    #: Speaker labels on batch results (``diarize=True``).
    diarization: bool
    #: Batch denoising before recognition (``denoise=True``); raises when unsupported.
    denoise: bool = False
    #: Longest single batch request in seconds; ``None`` = not limited by the provider.
    max_batch_seconds: float | None = None
    #: Free-text note on language coverage (e.g. which Indian languages).
    languages_note: str = ""


class TTSCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True)

    sample_rates: tuple[int, ...]
    voice_listing: bool
    speed_control: bool
    #: Voices are tied to a language (Google, Azure) rather than multilingual (Gnani, ElevenLabs).
    voices_per_language: bool = False
    languages_note: str = ""


class Voice(BaseModel):
    id: str
    name: str
    languages: list[str] = Field(default_factory=list)
    gender: str | None = None


class SynthesisResult(BaseModel):
    provider: SpeechProviderName
    voice: str
    audio: bytes = Field(repr=False)  # WAV, 16-bit mono linear PCM
    sample_rate: int = Field(gt=0)
    duration_s: float = Field(ge=0)
    usage: SpeechUsage


class SpeechSelection(BaseModel):
    """Per-agent or per-run provider override; ``None`` falls back to the environment default."""

    model_config = ConfigDict(extra="forbid")

    stt: SpeechProviderName | None = None
    tts: SpeechProviderName | None = None


class STTProvider(ABC):
    name: ClassVar[SpeechProviderName]
    capabilities: ClassVar[STTCapabilities]

    @abstractmethod
    async def transcribe(
        self,
        wav: bytes,
        language: str,
        *,
        diarize: bool = False,
        num_speakers: int | None = None,
        bias_words: list[str] | None = None,
        denoise: bool = False,
    ) -> Transcript:
        """Batch-transcribe a WAV recording (``denoise``: provider-side noise suppression)."""

    def transcribe_stream(
        self, pcm_chunks: AsyncIterator[bytes], language: str, *, sample_rate: int = 16000
    ) -> AsyncIterator[StreamingTranscript]:
        """Transcribe live audio; yields interim and final results as they arrive."""
        raise UnsupportedCapabilityError(f"{self.name.value} does not offer streaming STT")

    @abstractmethod
    async def aclose(self) -> None:
        """Release HTTP clients / sessions. Idempotent."""


class TTSProvider(ABC):
    name: ClassVar[SpeechProviderName]
    capabilities: ClassVar[TTSCapabilities]

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str | None,
        language: str,
        *,
        sample_rate: int = 16000,
        speed: float = 1.0,
    ) -> SynthesisResult:
        """Synthesize ``text`` to a WAV at ``sample_rate`` (``voice=None`` uses the env default)."""

    @abstractmethod
    async def list_voices(self, language: str | None = None) -> list[Voice]:
        """Voices the provider offers, optionally only those speaking ``language``."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release HTTP clients / sessions. Idempotent."""
