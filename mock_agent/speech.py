"""STT/TTS for the mock agent through the shared Gnani wrappers (``pareeksha.gnani``)."""

from __future__ import annotations

import asyncio
import io
import os
import wave
from pathlib import Path
from typing import Protocol

from pareeksha.gnani import GnaniSpeech, UsageLedger

AGENT_VOICE = "Avinash"
SAMPLE_RATE = 16_000


class Speech(Protocol):
    async def hear(self, pcm16: bytes, language: str) -> str: ...

    async def say(self, text: str, language: str) -> bytes: ...


def pcm_to_wav(pcm16: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm16)
    return buf.getvalue()


def wav_to_pcm(wav: bytes) -> bytes:
    with wave.open(io.BytesIO(wav)) as w:
        return bytes(w.readframes(w.getnframes()))


class GnaniAgentSpeech:
    """Real Gnani STT (REST) and TTS; TTS is disk-cached so repeated lines cost nothing."""

    def __init__(self, ledger: UsageLedger | None = None, cache_dir: Path | None = None) -> None:
        cache = cache_dir or Path(os.environ.get("MOCK_AGENT_TTS_CACHE", "/tmp/mock_agent_tts"))
        self.ledger = ledger if ledger is not None else UsageLedger()
        self._gnani = GnaniSpeech(
            os.environ.get("GNANI_API_KEY"), cache_dir=cache, ledger=self.ledger
        )

    def usage_totals(self) -> dict[str, dict[str, float]]:
        return self.ledger.totals()

    async def hear(self, pcm16: bytes, language: str) -> str:
        result = await asyncio.to_thread(self._gnani.transcribe, pcm_to_wav(pcm16), language)
        return str(result.get("transcript", ""))

    async def say(self, text: str, language: str) -> bytes:
        tts = await asyncio.to_thread(
            self._gnani.synthesize, text, AGENT_VOICE, language, sample_rate=SAMPLE_RATE
        )
        return wav_to_pcm(tts.audio)
