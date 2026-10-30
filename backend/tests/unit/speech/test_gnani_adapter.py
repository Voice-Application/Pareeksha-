"""Gnani adapter over fakes of the VOICE-01 wrapper and the SDK stream client (no network)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest
from gnani.stt.client import StreamTranscriptEvent
from gnani.stt.exceptions import APIError
from gnani.tts.exceptions import APIError as TTSAPIError

from pareeksha.gnani import GnaniSpeech, TTSResult
from pareeksha.speech import (
    SpeechConfigError,
    SpeechNoAudioError,
    SpeechPermanentError,
    SpeechRetryableError,
    UnsupportedCapabilityError,
)
from pareeksha.speech.providers.gnani import GnaniSTT, GnaniTTS

from .conftest import make_settings, make_wav

SETTINGS = make_settings(
    gnani_api_key="g-test",
    gnani_tts_voice="Lakshmi",
    cost_tts_per_1k_chars=10.0,
    cost_stt_rest_per_min=6.0,
    cost_stt_batch_per_min=3.0,
)


class FakeSpeech(GnaniSpeech):
    def __init__(self) -> None:
        super().__init__("k")
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.fail: Exception | None = None

    def transcribe(self, wav: bytes, language: str) -> dict[str, Any]:
        self.calls.append(("rest", (language,), {}))
        if self.fail:
            raise self.fail
        return {"transcript": "namaste", "model": "gnani-prisma-v2.5"}

    def transcribe_batch(self, wav: bytes, language: str, **kw: Any) -> list[dict[str, Any]]:
        self.calls.append(("batch", (language,), kw))
        return [
            {"start": 0.0, "end": 1.0, "text": "haan", "speaker": 1},
            {"start": 1.0, "end": 2.0, "text": "boliye", "speaker": None},
        ]

    def synthesize(self, text: str, voice: str, language: str, **kw: Any) -> TTSResult:
        self.calls.append(("tts", (text, voice, language), kw))
        if self.fail:
            raise self.fail
        wav = make_wav(1.5, kw["sample_rate"])
        return TTSResult(wav, kw["sample_rate"], 1.5, cached=len(self.calls) > 1)


async def test_rest_and_batch_transcribe() -> None:
    speech = FakeSpeech()
    stt = GnaniSTT(SETTINGS, speech=speech)
    rest = await stt.transcribe(make_wav(2.0), "kn-IN")
    assert rest.text == "namaste" and rest.model == "gnani-prisma-v2.5"
    assert rest.usage.operation == "stt_rest" and rest.usage.est_cost == pytest.approx(0.2)
    assert rest.segments[0].end_s == 2.0
    batch = await stt.transcribe(
        make_wav(2.0), "kn-IN", diarize=True, num_speakers=3, bias_words=["EMI"]
    )
    assert [s.speaker for s in batch.segments] == ["1", None]
    assert batch.text == "haan boliye" and batch.usage.operation == "stt_batch"
    assert batch.usage.est_cost == pytest.approx(0.1)
    assert speech.calls[1][2] == {"speakers": 3, "denoise": False, "bias_words": ["EMI"]}
    await stt.transcribe(make_wav(2.0), "kn-IN", diarize=True, denoise=True)
    assert speech.calls[2][2] == {"speakers": 2, "denoise": True, "bias_words": None}
    await stt.transcribe(make_wav(2.0), "kn-IN", denoise=True)  # denoise alone: batch, 1 speaker
    assert speech.calls[3][2] == {"speakers": 1, "denoise": True, "bias_words": None}
    with pytest.raises(UnsupportedCapabilityError):
        await stt.transcribe(make_wav(), "kn-IN", bias_words=["x"])


async def test_sdk_errors_are_mapped() -> None:
    speech = FakeSpeech()
    stt = GnaniSTT(SETTINGS, speech=speech)
    speech.fail = APIError(503, "boom")
    with pytest.raises(SpeechRetryableError):
        await stt.transcribe(make_wav(), "kn-IN")
    speech.fail = APIError(400, "bad")
    with pytest.raises(SpeechPermanentError):
        await stt.transcribe(make_wav(), "kn-IN")
    with pytest.raises(SpeechPermanentError):
        await GnaniTTS(SETTINGS, speech=speech).synthesize("x", None, "kn-IN")


async def test_tts_sdk_errors_are_mapped_too() -> None:
    """The TTS client raises its own ``APIError`` class (distinct from the STT one)."""
    speech = FakeSpeech()
    tts = GnaniTTS(SETTINGS, speech=speech)
    speech.fail = TTSAPIError(429, "Only 1 active request is allowed at a time")
    with pytest.raises(SpeechRetryableError):
        await tts.synthesize("x", "Lakshmi", "kn-IN")
    speech.fail = TTSAPIError(400, "bad voice")
    with pytest.raises(SpeechPermanentError):
        await tts.synthesize("x", "Lakshmi", "kn-IN")


async def test_no_audio_generated_maps_to_a_permanent_no_audio_error() -> None:
    speech = FakeSpeech()
    speech.fail = TTSAPIError(500, "No audio generated during synthesis")
    with pytest.raises(SpeechNoAudioError):
        await GnaniTTS(SETTINGS, speech=speech).synthesize("...", "Lakshmi", "hi-IN")
    speech.fail = TTSAPIError(500, "internal error")
    with pytest.raises(SpeechRetryableError):
        await GnaniTTS(SETTINGS, speech=speech).synthesize("hi", "Lakshmi", "hi-IN")


async def test_tts_wav_voices_and_cache_accounting(tmp_path: Path) -> None:
    speech = FakeSpeech()
    tts = GnaniTTS(SETTINGS, speech=speech, cache_dir=tmp_path)
    assert speech.cache_dir == tmp_path
    first = await tts.synthesize("namaste", None, "kn-IN", sample_rate=8000, speed=1.1)
    assert first.sample_rate == 8000 and first.duration_s == 1.5 and first.voice == "Lakshmi"
    assert speech.calls[0][2] == {"speed": 1.1, "sample_rate": 8000, "model": "timbre-v3.0"}
    assert first.usage.characters == 7 and first.usage.est_cost == pytest.approx(0.07)
    second = await tts.synthesize("namaste", "Avinash", "kn-IN")
    assert second.usage.characters == 0 and second.usage.est_cost is None
    voices = await tts.list_voices("hi-IN")
    assert len(voices) == 13 and "Lakshmi" in {v.id for v in voices}
    with pytest.raises(SpeechPermanentError, match="voice"):
        await GnaniTTS(make_settings(gnani_api_key="k"), speech=speech).synthesize(
            "x", None, "kn-IN"
        )


def test_missing_key_without_injected_speech(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SpeechConfigError, match="GNANI_API_KEY"):
        GnaniSTT(make_settings())
    assert GnaniSTT(SETTINGS)._speech.ledger.records == []


class FakeStream:
    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False
        self.fail_connect: Exception | None = None
        self._queue: asyncio.Queue[Any] = asyncio.Queue()

    async def connect(self) -> None:
        if self.fail_connect:
            raise self.fail_connect

    async def send_audio(self, chunk: bytes) -> None:
        self.sent.append(chunk)

    async def close(self) -> list[Any]:
        if not self.closed:
            self.closed = True
            await self._queue.put(StreamTranscriptEvent("namaste", 900, "s1", "0", 120, "t", {}))
            await self._queue.put(StreamTranscriptEvent("", 10, "s2", "1", 5, "t", {}))
            await self._queue.put(object())  # non-transcript events are ignored
            await self._queue.put(None)
        return []

    async def __aiter__(self) -> AsyncIterator[Any]:
        while True:
            item = await self._queue.get()
            if item is None:
                return
            yield item


async def _pcm(n: int, size: int = 700) -> AsyncIterator[bytes]:
    for _ in range(n):
        yield b"\x01\x00" * (size // 2)


async def test_streaming_frames_and_events() -> None:
    fake = FakeStream()
    stt = GnaniSTT(
        SETTINGS,
        speech=FakeSpeech(),
        stream_client_factory=lambda lang, rate: fake,
        stream_tail_s=0.1,
        pace=False,
    )
    events = [e async for e in stt.transcribe_stream(_pcm(5), "kn-IN")]
    assert [(e.text, e.is_final, e.end_s) for e in events] == [("namaste", True, 0.9)]
    assert fake.closed and all(len(c) == 1024 for c in fake.sent)
    # 3 full frames, the 428-byte remainder padded to a frame, then 3200 silence bytes = 4 frames
    assert len(fake.sent) == 8


async def test_streaming_connect_failure_and_early_exit() -> None:
    fake = FakeStream()
    fake.fail_connect = ConnectionError("down")
    stt = GnaniSTT(SETTINGS, speech=FakeSpeech(), stream_client_factory=lambda lang, rate: fake)
    with pytest.raises(SpeechRetryableError):
        _ = [e async for e in stt.transcribe_stream(_pcm(1), "kn-IN")]
    ok = FakeStream()
    stt2 = GnaniSTT(
        SETTINGS,
        speech=FakeSpeech(),
        stream_client_factory=lambda lang, rate: ok,
        stream_tail_s=0.05,
        pace=False,
    )
    gen = stt2.transcribe_stream(_pcm(2), "kn-IN")
    first = await anext(gen)
    assert first.text == "namaste"
    await cast(AsyncGenerator[Any, None], gen).aclose()
    assert ok.closed
    await stt2.aclose()
    await GnaniTTS(SETTINGS, speech=FakeSpeech()).aclose()


async def test_streaming_pacing_and_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeStream()
    stt = GnaniSTT(
        SETTINGS,
        speech=FakeSpeech(),
        stream_client_factory=lambda lang, rate: fake,
        stream_tail_s=0.0,
        pace=True,
    )
    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def quick(delay: float) -> None:
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", quick)
    events = [e async for e in stt.transcribe_stream(_pcm(0), "kn-IN")]
    assert [e.text for e in events] == ["namaste"] and 1.5 in delays
