"""Thin wrappers over the official ``gnani-vachana`` SDK.

Adds what the TRD asks for (docs/03-TRD.md section 3): every call is recorded
in a usage ledger, 5xx and timeouts are retried with backoff, and TTS output is
cached on disk keyed by sha256(model|voice|language|speed|rate|encoding|text).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import random
import time
import wave
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import requests
from gnani.stt import GnaniSTTBatchClient, GnaniSTTClient, GnaniSTTStreamClient
from gnani.stt.client import StreamTranscriptEvent
from gnani.stt.exceptions import APIError
from gnani.tts import AudioConfig, GnaniTTSClient
from gnani.tts.exceptions import APIError as TTSAPIError

T = TypeVar("T")

TTS_MODEL = "timbre-v3.0"
STREAM_CHUNK_BYTES = 1024  # 512 samples of 16-bit PCM, per the STT WebSocket spec


@dataclass
class UsageRecord:
    kind: str  # tts | stt_rest | stt_stream | stt_batch
    language: str
    audio_seconds: float = 0.0
    chars: int = 0
    cached: bool = False
    latency_ms: int = 0
    detail: str = ""


@dataclass
class UsageLedger:
    """Counts every Gnani request and the audio seconds it touched."""

    records: list[UsageRecord] = field(default_factory=list)

    def add(self, record: UsageRecord) -> None:
        self.records.append(record)

    def totals(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for r in self.records:
            if r.cached:
                continue
            row = out.setdefault(r.kind, {"calls": 0, "audio_seconds": 0.0, "chars": 0})
            row["calls"] += 1
            row["audio_seconds"] = round(row["audio_seconds"] + r.audio_seconds, 3)
            row["chars"] += r.chars
        return out

    def as_dicts(self) -> list[dict[str, Any]]:
        return [asdict(r) for r in self.records]


@dataclass
class TTSResult:
    audio: bytes  # WAV container, linear PCM
    sample_rate: int
    seconds: float
    cached: bool


def normalize_wav(data: bytes) -> bytes:
    """Rewrite the RIFF header from the real payload length.

    Gnani's TTS returns a streaming-style WAV header whose size fields are
    0xFFFFFFFF, so ``wave`` reports ~134,000 s for a 5 s clip.
    """
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE payload")
    pos, fmt = 12, None
    while pos + 8 <= len(data):
        cid = data[pos : pos + 4]
        size = int.from_bytes(data[pos + 4 : pos + 8], "little")
        if cid == b"fmt ":
            channels = int.from_bytes(data[pos + 10 : pos + 12], "little")
            rate = int.from_bytes(data[pos + 12 : pos + 16], "little")
            width = int.from_bytes(data[pos + 22 : pos + 24], "little") // 8
            fmt = (channels, rate, width)
        elif cid == b"data":
            if fmt is None:
                break
            start = pos + 8
            end = len(data) if size == 0xFFFFFFFF or start + size > len(data) else start + size
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(fmt[0])
                w.setframerate(fmt[1])
                w.setsampwidth(fmt[2])
                w.writeframes(data[start:end])
            return buf.getvalue()
        pos += 8 + size + (size & 1)
    raise ValueError("WAV has no fmt/data chunks")


def wav_duration_s(data: bytes) -> float:
    with wave.open(io.BytesIO(normalize_wav(data))) as w:
        return float(w.getnframes() / w.getframerate())


def cache_key(
    model: str,
    voice: str,
    language: str,
    speed: float,
    rate: int,
    encoding: str,
    text: str,
) -> str:
    raw = "|".join([model, voice, language, f"{speed:.3f}", str(rate), encoding, text])
    return hashlib.sha256(raw.encode()).hexdigest()


def is_retryable(exc: BaseException) -> bool:
    """5xx, 429, timeouts and broken connections retry; other 4xx never do (TRD section 3).

    429 is retried because Gnani allows one active request per key ("Only 1 active request is
    allowed at a time"), so concurrent callers sharing a key collide briefly. The TTS client raises
    its own ``APIError`` class, distinct from the STT one. Transport faults (``requests`` raises
    ``ChunkedEncodingError`` for a connection dropped mid-body, which is not a ``ConnectionError``)
    are retryable too.
    """
    if isinstance(exc, APIError | TTSAPIError):
        if "no audio generated" in str(exc).lower():
            return False  # the same text yields no audio every time
        return exc.status_code >= 500 or exc.status_code == 429
    return isinstance(
        exc,
        (
            requests.Timeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
            TimeoutError,
            ConnectionError,
        ),
    )


#: Retryable failures (429 busy key, 5xx, dropped connections) back off with jitter and keep
#: trying until about a minute of waiting has been spent: concurrent processes sharing the key
#: each pick their own delay, which de-synchronizes them. ``MAX_ATTEMPTS`` bounds a zero delay.
RETRY_BUDGET_S = 60.0
RETRY_MAX_DELAY_S = 8.0
RATE_LIMIT_MAX_WAIT_S = 3.0
MAX_ATTEMPTS = 40


def _is_rate_limited(exc: BaseException) -> bool:
    return isinstance(exc, APIError | TTSAPIError) and exc.status_code == 429


def _retry(fn: Callable[[], T], *, base_delay: float = 1.0) -> T:
    waited = 0.0
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc):
                raise
            attempt += 1
            if _is_rate_limited(exc):
                delay = random.uniform(0.2, min(RATE_LIMIT_MAX_WAIT_S, 0.5 + 0.25 * attempt))
            else:
                ceiling = min(RETRY_MAX_DELAY_S, base_delay * 2 ** (attempt - 1))
                delay = random.uniform(ceiling / 2, ceiling)
            waited += delay
            if attempt >= MAX_ATTEMPTS or waited > RETRY_BUDGET_S:
                raise
            time.sleep(delay)


class GnaniSpeech:
    """TTS and STT entry points used by the simulator, auditor and scripts."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        cache_dir: Path | None = None,
        ledger: UsageLedger | None = None,
        retry_delay: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self.cache_dir = cache_dir
        self.ledger = ledger if ledger is not None else UsageLedger()
        self._retry_delay = retry_delay

    # -- TTS -------------------------------------------------------------
    def synthesize(
        self,
        text: str,
        voice: str,
        language: str,
        *,
        speed: float = 1.0,
        sample_rate: int = 16000,
        model: str = TTS_MODEL,
    ) -> TTSResult:
        key = cache_key(model, voice, language, speed, sample_rate, "linear_pcm", text)
        path = self.cache_dir / f"{key}.wav" if self.cache_dir else None
        if path is not None and path.exists():
            audio = normalize_wav(path.read_bytes())
            secs = wav_duration_s(audio)
            self.ledger.add(UsageRecord("tts", language, secs, len(text), cached=True))
            return TTSResult(audio, sample_rate, secs, True)

        client = GnaniTTSClient(self._api_key)
        cfg = AudioConfig(sample_rate=sample_rate, encoding="linear_pcm", container="wav")
        t0 = time.monotonic()
        audio = _retry(
            lambda: client.synthesize(
                text,
                voice,
                model=model,
                language=language,
                speed=speed,
                audio_config=cfg,
            ),
            base_delay=self._retry_delay,
        )
        audio = normalize_wav(audio)
        secs = wav_duration_s(audio)
        self.ledger.add(
            UsageRecord(
                "tts",
                language,
                secs,
                len(text),
                latency_ms=int((time.monotonic() - t0) * 1000),
                detail=f"{model}/{voice}",
            )
        )
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(audio)
        return TTSResult(audio, sample_rate, secs, False)

    # -- STT REST --------------------------------------------------------
    def transcribe(self, wav: bytes, language: str) -> dict[str, Any]:
        client = GnaniSTTClient(self._api_key)
        t0 = time.monotonic()
        result = _retry(
            lambda: client.transcribe_bytes(wav, "audio.wav", language),
            base_delay=self._retry_delay,
        )
        self.ledger.add(
            UsageRecord(
                "stt_rest",
                language,
                wav_duration_s(wav),
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        )
        return result

    # -- STT stream ------------------------------------------------------
    async def transcribe_stream(
        self,
        pcm16: bytes,
        language: str,
        *,
        sample_rate: int = 16000,
        tail_s: float = 3.0,
    ) -> list[StreamTranscriptEvent]:
        """Stream raw 16-bit mono PCM at real-time pace and collect transcripts."""
        stream = GnaniSTTStreamClient(self._api_key, language, sample_rate=sample_rate)
        t0 = time.monotonic()
        await stream.connect()
        pace = STREAM_CHUNK_BYTES / 2 / sample_rate
        # pad with silence so server VAD sees end-of-speech
        padded = pcm16 + b"\x00" * int(tail_s * sample_rate * 2)
        try:
            for i in range(0, len(padded), STREAM_CHUNK_BYTES):
                chunk = padded[i : i + STREAM_CHUNK_BYTES].ljust(STREAM_CHUNK_BYTES, b"\x00")
                await stream.send_audio(chunk)
                await asyncio.sleep(pace)
            await asyncio.sleep(1.5)
        finally:
            events = await stream.close()
        self.ledger.add(
            UsageRecord(
                "stt_stream",
                language,
                len(pcm16) / 2 / sample_rate,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        )
        return events

    # -- STT batch -------------------------------------------------------
    def transcribe_batch(
        self,
        wav: bytes,
        language: str,
        *,
        speakers: int = 2,
        denoise: bool = False,
        bias_words: Iterable[str] | None = None,
        timeout: float = 600,
    ) -> list[dict[str, Any]]:
        """Batch STT with diarization; returns segments as plain dicts."""
        client = GnaniSTTBatchClient(self._api_key)
        t0 = time.monotonic()
        result = client.transcribe(
            [("call.wav", wav)],
            language,
            speakers=speakers,
            denoise=denoise,
            bias_words=list(bias_words) if bias_words else None,
            timeout=timeout,
            progress=False,
        )
        segments = [
            {"start": s.start, "end": s.end, "text": s.text, "speaker": s.speaker}
            for s in result[0].segments
        ]
        self.ledger.add(
            UsageRecord(
                "stt_batch",
                language,
                wav_duration_s(wav),
                latency_ms=int((time.monotonic() - t0) * 1000),
                detail=f"speakers={speakers}",
            )
        )
        return segments
