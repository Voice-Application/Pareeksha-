"""Gnani wrapper behaviour with the SDK clients replaced by fakes (no network)."""

from __future__ import annotations

import asyncio
import io
import struct
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
import requests
from gnani.stt.exceptions import APIError

from pareeksha.gnani import clients
from pareeksha.gnani.clients import (
    GnaniSpeech,
    UsageLedger,
    UsageRecord,
    cache_key,
    is_retryable,
    normalize_wav,
    wav_duration_s,
)


def make_wav(seconds: float = 1.0, rate: int = 16000, streaming_header: bool = False) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    data = bytearray(buf.getvalue())
    if streaming_header:
        data[4:8] = struct.pack("<I", 0xFFFFFFFF)
        data[40:44] = struct.pack("<I", 0xFFFFFFFF)
    return bytes(data)


def test_streaming_header_duration_is_real() -> None:
    wav = make_wav(2.0, streaming_header=True)
    assert wav_duration_s(wav) == pytest.approx(2.0)
    fixed = normalize_wav(wav)
    with wave.open(io.BytesIO(fixed)) as w:
        assert w.getnframes() == 32000


def test_normalize_rejects_garbage_and_missing_data() -> None:
    with pytest.raises(ValueError):
        normalize_wav(b"not a wav at all")
    with pytest.raises(ValueError):
        normalize_wav(make_wav(0.1)[:36])


def test_normalize_skips_odd_chunks() -> None:
    wav = make_wav(0.5)
    extra = b"LIST" + struct.pack("<I", 3) + b"abc" + b"\x00"
    with_list = wav[:36] + extra + wav[36:]
    assert wav_duration_s(with_list) == pytest.approx(0.5)


def test_cache_key_depends_on_every_field() -> None:
    base: dict[str, Any] = {
        "model": "timbre-v3.0",
        "voice": "Lakshmi",
        "language": "kn-IN",
        "speed": 1.0,
        "rate": 16000,
        "encoding": "linear_pcm",
        "text": "ನಮಸ್ಕಾರ",
    }
    keys = {cache_key(**base)}
    variants: list[dict[str, Any]] = [
        {"model": "timbre-v2.5"},
        {"voice": "Avinash"},
        {"language": "hi-IN"},
        {"speed": 1.1},
        {"rate": 8000},
        {"encoding": "pcm_mulaw"},
        {"text": "x"},
    ]
    for v in variants:
        keys.add(cache_key(**{**base, **v}))
    assert len(keys) == len(variants) + 1
    assert cache_key(**base) == cache_key(**base)


def test_is_retryable() -> None:
    assert is_retryable(APIError(503, "x"))
    assert not is_retryable(APIError(400, "x"))
    assert not is_retryable(APIError(401, "x"))
    assert is_retryable(requests.Timeout())
    assert is_retryable(requests.ConnectionError())
    assert not is_retryable(ValueError("x"))


def test_rate_limits_and_tts_errors_are_retryable() -> None:
    """Gnani allows one active request per key; the TTS client has its own APIError class."""
    from gnani.tts.exceptions import APIError as TTSAPIError

    assert is_retryable(APIError(429, "x")) and is_retryable(TTSAPIError(429, "x"))
    assert is_retryable(TTSAPIError(503, "x"))
    assert not is_retryable(TTSAPIError(400, "x")) and not is_retryable(TTSAPIError(401, "x"))


def test_ledger_totals_ignore_cache_hits() -> None:
    ledger = UsageLedger()
    ledger.add(UsageRecord("tts", "kn-IN", 2.0, 10))
    ledger.add(UsageRecord("tts", "kn-IN", 3.0, 5))
    ledger.add(UsageRecord("tts", "kn-IN", 9.0, 99, cached=True))
    ledger.add(UsageRecord("stt_rest", "hi-IN", 1.5))
    assert ledger.totals() == {
        "tts": {"calls": 2, "audio_seconds": 5.0, "chars": 15},
        "stt_rest": {"calls": 1, "audio_seconds": 1.5, "chars": 0},
    }
    assert ledger.as_dicts()[3]["kind"] == "stt_rest"


class FakeTTS:
    calls: ClassVar[list[dict[str, Any]]] = []
    fail_times = 0

    def __init__(self, api_key: str | None = None) -> None:
        pass

    def synthesize(self, text: str, voice: str, **kw: Any) -> bytes:
        FakeTTS.calls.append({"text": text, "voice": voice, **kw})
        if FakeTTS.fail_times:
            FakeTTS.fail_times -= 1
            raise APIError(503, "busy")
        return make_wav(1.5, streaming_header=True)


@pytest.fixture(autouse=True)
def _reset_fake() -> None:
    FakeTTS.calls = []
    FakeTTS.fail_times = 0


def test_synthesize_caches_and_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clients, "GnaniTTSClient", FakeTTS)
    g = GnaniSpeech("k", cache_dir=tmp_path, retry_delay=0)
    first = g.synthesize("hello", "Lakshmi", "kn-IN", speed=1.1)
    second = g.synthesize("hello", "Lakshmi", "kn-IN", speed=1.1)
    assert not first.cached and second.cached
    assert first.seconds == pytest.approx(1.5)
    assert len(FakeTTS.calls) == 1
    assert FakeTTS.calls[0]["model"] == "timbre-v3.0"
    assert FakeTTS.calls[0]["speed"] == 1.1
    assert g.ledger.totals()["tts"]["calls"] == 1
    assert len(g.ledger.records) == 2


def test_synthesize_retries_5xx_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clients, "GnaniTTSClient", FakeTTS)
    FakeTTS.fail_times = 2
    g = GnaniSpeech("k", retry_delay=0)
    assert g.synthesize("hi", "Shivani", "hi-IN").seconds == pytest.approx(1.5)
    assert len(FakeTTS.calls) == 3


def test_synthesize_does_not_retry_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    class Bad(FakeTTS):
        def synthesize(self, *a: Any, **kw: Any) -> bytes:
            FakeTTS.calls.append({})
            raise APIError(400, "bad voice")

    monkeypatch.setattr(clients, "GnaniTTSClient", Bad)
    with pytest.raises(APIError):
        GnaniSpeech("k", retry_delay=0).synthesize("hi", "x", "hi-IN")
    assert len(FakeTTS.calls) == 1


def test_synthesize_gives_up_after_three_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clients, "GnaniTTSClient", FakeTTS)
    FakeTTS.fail_times = 99
    with pytest.raises(APIError):
        GnaniSpeech("k", retry_delay=0).synthesize("hi", "x", "hi-IN")
    assert len(FakeTTS.calls) == 3


def test_transcribe_rest_records_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSTT:
        def __init__(self, api_key: str | None = None) -> None:
            pass

        def transcribe_bytes(self, audio: bytes, name: str, lang: str) -> dict[str, str]:
            return {"transcript": "नमस्ते", "model": "m"}

    monkeypatch.setattr(clients, "GnaniSTTClient", FakeSTT)
    g = GnaniSpeech("k")
    assert g.transcribe(make_wav(2.0), "hi-IN")["transcript"] == "नमस्ते"
    assert g.ledger.totals()["stt_rest"] == {
        "calls": 1,
        "audio_seconds": 2.0,
        "chars": 0,
    }


@pytest.mark.asyncio
async def test_transcribe_stream_paces_pads_and_collects(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[bytes] = []

    class FakeStream:
        def __init__(self, api_key: str, lang: str, sample_rate: int) -> None:
            self.rate = sample_rate

        async def connect(self) -> None:
            return None

        async def send_audio(self, chunk: bytes) -> None:
            sent.append(chunk)

        async def close(self) -> list[SimpleNamespace]:
            return [SimpleNamespace(text="ok")]

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(clients, "GnaniSTTStreamClient", FakeStream)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    g = GnaniSpeech("k")
    pcm = b"\x01\x00" * 16000  # 1 s
    events = await g.transcribe_stream(pcm, "hi-IN", tail_s=1.0)
    assert [e.text for e in events] == ["ok"]
    assert all(len(c) == 1024 for c in sent)
    assert sum(len(c) for c in sent) >= len(pcm) + 32000  # one second of silence appended
    assert g.ledger.totals()["stt_stream"]["audio_seconds"] == pytest.approx(1.0)


def test_transcribe_batch_returns_plain_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    def seg(s: float, e: float, t: str, sp: int) -> SimpleNamespace:
        return SimpleNamespace(start=s, end=e, text=t, speaker=sp)

    class FakeBatch:
        args: ClassVar[dict[str, Any]] = {}

        def __init__(self, api_key: str | None = None) -> None:
            pass

        def transcribe(self, files: list[Any], lang: str, **kw: Any) -> list[SimpleNamespace]:
            FakeBatch.args = {"files": files, "lang": lang, **kw}
            return [SimpleNamespace(segments=[seg(0, 1, "a", 1), seg(1, 2, "b", 2)])]

    monkeypatch.setattr(clients, "GnaniSTTBatchClient", FakeBatch)
    g = GnaniSpeech("k")
    out = g.transcribe_batch(make_wav(2.0), "kn-IN", bias_words=["EMI"])
    assert [(s["speaker"], s["text"]) for s in out] == [(1, "a"), (2, "b")]
    assert FakeBatch.args["speakers"] == 2
    assert FakeBatch.args["bias_words"] == ["EMI"]
    assert g.ledger.totals()["stt_batch"]["calls"] == 1
