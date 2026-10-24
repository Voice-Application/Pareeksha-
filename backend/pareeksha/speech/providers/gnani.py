"""Gnani adapter: wraps ``pareeksha.gnani`` (VOICE-01) without changing its public API.

Batch STT without diarization uses the REST endpoint (``/stt/v3``); with ``diarize=True`` it uses
the batch-job endpoint (2+ speakers). Streaming uses the ``gnani-vachana`` WebSocket client
directly so results are yielded as the server VAD emits them.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from gnani.stt import GnaniSTTStreamClient
from gnani.stt.client import StreamTranscriptEvent
from gnani.stt.exceptions import APIError
from gnani.tts import TIMBRE_V30_VOICES

from pareeksha.gnani import GnaniSpeech, is_retryable, wav_duration_s
from pareeksha.speech.base import (
    SpeechConfigError,
    SpeechError,
    SpeechPermanentError,
    SpeechProviderName,
    SpeechRetryableError,
    SpeechUsage,
    StreamingTranscript,
    STTCapabilities,
    STTProvider,
    SynthesisResult,
    Transcript,
    TranscriptSegment,
    TTSCapabilities,
    TTSProvider,
    UnsupportedCapabilityError,
    Voice,
)
from pareeksha.speech.config import SpeechSettings
from pareeksha.speech.providers._common import elapsed_ms

FRAME_BYTES = 1024  # 512 samples of 16-bit PCM, per the Gnani WebSocket spec
GNANI_LANGUAGES = [
    "bn-IN",
    "en-IN",
    "gu-IN",
    "hi-IN",
    "kn-IN",
    "ml-IN",
    "mr-IN",
    "pa-IN",
    "ta-IN",
    "te-IN",
]


def _make_speech(
    settings: SpeechSettings | None, speech: GnaniSpeech | None
) -> tuple[SpeechSettings, GnaniSpeech]:
    s = settings or SpeechSettings()
    missing = s.missing_env(SpeechProviderName.GNANI)
    if missing and speech is None:
        raise SpeechConfigError(f"gnani: set {', '.join(missing)} in .env")
    return s, speech or GnaniSpeech(s.gnani_api_key)


def _map_error(exc: Exception) -> SpeechError:
    if isinstance(exc, SpeechError):
        return exc
    if is_retryable(exc) or isinstance(exc, OSError):
        return SpeechRetryableError(f"gnani: {type(exc).__name__}: {exc}")
    return SpeechPermanentError(f"gnani: {type(exc).__name__}: {exc}")


class GnaniSTT(STTProvider):
    name = SpeechProviderName.GNANI
    capabilities = STTCapabilities(
        streaming=True,
        word_timings=False,
        word_confidence=False,
        diarization=True,
        denoise=True,
        languages_note="bn hi en gu kn ml mr pa ta te (-IN); Indian-language specialist",
    )

    def __init__(
        self,
        settings: SpeechSettings | None = None,
        *,
        speech: GnaniSpeech | None = None,
        stream_client_factory: Callable[[str, int], Any] | None = None,
        stream_tail_s: float = 3.0,
        pace: bool = True,
    ) -> None:
        self.settings, self._speech = _make_speech(settings, speech)
        self._stream_factory = stream_client_factory or (
            lambda lang, rate: GnaniSTTStreamClient(
                self.settings.gnani_api_key, lang, sample_rate=rate
            )
        )
        self._tail_s = stream_tail_s
        self._pace = pace

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
        duration = wav_duration_s(wav)
        t0 = time.monotonic()
        try:
            if diarize or denoise:
                segs = await asyncio.to_thread(
                    self._speech.transcribe_batch,
                    wav,
                    language,
                    speakers=num_speakers or (2 if diarize else 1),
                    denoise=denoise,
                    bias_words=bias_words,
                )
                segments = [
                    TranscriptSegment(
                        text=str(s["text"]),
                        start_s=float(s["start"]),
                        end_s=float(s["end"]),
                        speaker=str(s["speaker"]) if s.get("speaker") is not None else None,
                    )
                    for s in segs
                ]
                text, model, op = " ".join(s.text for s in segments), None, "stt_batch"
            else:
                if bias_words:
                    raise UnsupportedCapabilityError(
                        "gnani REST STT has no bias words; use diarize=True"
                    )
                res = await asyncio.to_thread(self._speech.transcribe, wav, language)
                text, model, op = str(res.get("transcript", "")), res.get("model"), "stt_rest"
                segments = (
                    [TranscriptSegment(text=text, start_s=0.0, end_s=duration)] if text else []
                )
        except (APIError, OSError, TimeoutError) as exc:
            raise _map_error(exc) from exc
        return Transcript(
            provider=self.name,
            model=str(model) if model else None,
            text=text,
            language=language,
            duration_s=duration,
            segments=segments,
            usage=SpeechUsage(
                provider=self.name,
                operation=op,
                audio_seconds=duration,
                latency_ms=elapsed_ms(t0),
                est_cost=self.settings.stt_cost(self.name, duration, op),
            ),
        )

    async def transcribe_stream(
        self, pcm_chunks: AsyncIterator[bytes], language: str, *, sample_rate: int = 16000
    ) -> AsyncIterator[StreamingTranscript]:
        stream = self._stream_factory(language, sample_rate)
        try:
            await stream.connect()
        except Exception as exc:
            raise _map_error(exc) from exc
        frame_s = FRAME_BYTES / 2 / sample_rate

        async def pump() -> None:
            buf = b""
            async for chunk in pcm_chunks:
                buf += chunk
                while len(buf) >= FRAME_BYTES:
                    await stream.send_audio(buf[:FRAME_BYTES])
                    buf = buf[FRAME_BYTES:]
                    if self._pace:
                        await asyncio.sleep(frame_s)
            # flush the remainder and add trailing silence so the server VAD closes the segment
            buf = buf.ljust(FRAME_BYTES, b"\x00") if buf else b""
            silence = b"\x00" * int(self._tail_s * sample_rate * 2)
            pending = buf + silence
            for i in range(0, len(pending), FRAME_BYTES):
                await stream.send_audio(pending[i : i + FRAME_BYTES].ljust(FRAME_BYTES, b"\x00"))
                if self._pace:
                    await asyncio.sleep(frame_s)
            if self._pace:
                await asyncio.sleep(1.5)
            await stream.close()

        sender = asyncio.create_task(pump())
        try:
            async for event in stream:
                if isinstance(event, StreamTranscriptEvent) and event.text:
                    yield StreamingTranscript(
                        text=event.text, is_final=True, end_s=event.audio_duration_ms / 1000
                    )
            await sender
        finally:
            if not sender.done():
                sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sender
            with contextlib.suppress(Exception):
                await stream.close()

    async def aclose(self) -> None:
        return None


class GnaniTTS(TTSProvider):
    name = SpeechProviderName.GNANI
    capabilities = TTSCapabilities(
        sample_rates=(8000, 16000, 22050, 24000, 44100, 48000),
        voice_listing=True,
        speed_control=True,
        languages_note="Timbre v3.0: 13 voices, each speaks all 10 Indian languages",
    )

    def __init__(
        self,
        settings: SpeechSettings | None = None,
        *,
        speech: GnaniSpeech | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.settings, self._speech = _make_speech(settings, speech)
        if cache_dir is not None:
            self._speech.cache_dir = cache_dir

    async def synthesize(
        self,
        text: str,
        voice: str | None,
        language: str,
        *,
        sample_rate: int = 16000,
        speed: float = 1.0,
    ) -> SynthesisResult:
        voice_name = voice or self.settings.gnani_tts_voice
        if not voice_name:
            raise SpeechPermanentError("gnani TTS needs a voice (arg or GNANI_TTS_VOICE)")
        t0 = time.monotonic()
        try:
            res = await asyncio.to_thread(
                self._speech.synthesize,
                text,
                voice_name,
                language,
                speed=speed,
                sample_rate=sample_rate,
                model=self.settings.gnani_tts_model,
            )
        except (APIError, OSError, TimeoutError) as exc:
            raise _map_error(exc) from exc
        return SynthesisResult(
            provider=self.name,
            voice=voice_name,
            audio=res.audio,
            sample_rate=res.sample_rate,
            duration_s=res.seconds,
            usage=SpeechUsage(
                provider=self.name,
                operation="tts",
                audio_seconds=0.0 if res.cached else res.seconds,
                characters=0 if res.cached else len(text),
                latency_ms=elapsed_ms(t0),
                est_cost=None if res.cached else self.settings.tts_cost(self.name, len(text)),
            ),
        )

    async def list_voices(self, language: str | None = None) -> list[Voice]:
        # Timbre v3.0 voices each speak every supported language, so the language filter keeps all.
        return [
            Voice(id=v, name=v, languages=list(GNANI_LANGUAGES)) for v in sorted(TIMBRE_V30_VOICES)
        ]

    async def aclose(self) -> None:
        return None
