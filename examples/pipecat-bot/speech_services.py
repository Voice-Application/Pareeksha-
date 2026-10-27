"""Pipecat STT/TTS services backed by ``pareeksha.speech`` providers (Gnani by default).

``pipecat-gnani`` 0.5.12 does not import against ``gnani-vachana`` 0.8.2 (it needs
``TIMBRE_V20_VOICES``), so the example wraps the platform's own provider interface instead. Any
provider selected with ``STT_PROVIDER`` / ``TTS_PROVIDER`` (or a ``SpeechSelection``) works.
"""

from __future__ import annotations

import io
import wave
from collections.abc import AsyncGenerator, Callable

from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame, TTSAudioRawFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from pareeksha.speech.base import STTProvider, TTSProvider
from pareeksha.speech.wav import pcm_to_wav

SAMPLE_RATE = 16_000
#: ~100 ms of 16 kHz mono PCM16 per frame handed to the pipeline.
CHUNK_BYTES = 3_200


class ProviderSTTService(SegmentedSTTService):
    """Batch-transcribes each VAD-delimited speech segment with a ``pareeksha.speech`` provider."""

    def __init__(
        self, provider: STTProvider, language: Callable[[], str], **kwargs: object
    ) -> None:
        super().__init__(sample_rate=SAMPLE_RATE, **kwargs)  # type: ignore[arg-type]
        self._provider = provider
        self._language = language

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        language = self._language()
        try:
            result = await self._provider.transcribe(pcm_to_wav(audio, SAMPLE_RATE), language)
        except Exception as exc:  # provider errors must not kill the call
            yield ErrorFrame(f"stt failed: {exc}")
            return
        text = result.text.strip()
        if text:
            yield TranscriptionFrame(text, "caller", time_now_iso8601())


class ProviderTTSService(TTSService):
    """Synthesises each text chunk with a ``pareeksha.speech`` provider."""

    def __init__(
        self,
        provider: TTSProvider,
        language: Callable[[], str],
        voice: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(sample_rate=SAMPLE_RATE, **kwargs)  # type: ignore[arg-type]
        self._provider = provider
        self._language = language
        self._voice = voice

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        try:
            result = await self._provider.synthesize(
                text, self._voice, self._language(), sample_rate=SAMPLE_RATE
            )
        except Exception as exc:
            yield ErrorFrame(f"tts failed: {exc}")
            return
        with wave.open(io.BytesIO(result.audio)) as wav:
            pcm = wav.readframes(wav.getnframes())
        for i in range(0, len(pcm), CHUNK_BYTES):
            yield TTSAudioRawFrame(pcm[i : i + CHUNK_BYTES], SAMPLE_RATE, 1, context_id=context_id)
