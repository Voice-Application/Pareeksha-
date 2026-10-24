"""Deepgram adapter. REST is mocked with respx; the WebSocket runs against a local test server."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from urllib.parse import parse_qs

import httpx
import pytest
import respx
from websockets.asyncio.server import ServerConnection, serve

from pareeksha.speech import (
    SpeechPermanentError,
    SpeechRetryableError,
    UnsupportedCapabilityError,
)
from pareeksha.speech.providers.deepgram import DeepgramSTT, DeepgramTTS, deepgram_language
from pareeksha.speech.wav import pcm_to_wav

from .conftest import make_settings, make_wav

SETTINGS = make_settings(
    deepgram_api_key="dg-test",
    cost_deepgram_stt_per_min=0.6,
    cost_deepgram_tts_per_1k_chars=3.0,
)

LISTEN = {
    "metadata": {"duration": 2.0},
    "results": {
        "channels": [
            {
                "alternatives": [
                    {
                        "transcript": "hello there friend",
                        "confidence": 0.97,
                        "words": [
                            {
                                "word": "hello",
                                "punctuated_word": "Hello",
                                "start": 0.0,
                                "end": 0.5,
                                "confidence": 0.99,
                                "speaker": 0,
                            },
                            {
                                "word": "there",
                                "start": 0.5,
                                "end": 0.9,
                                "confidence": 0.95,
                                "speaker": 0,
                            },
                            {
                                "word": "friend",
                                "start": 1.0,
                                "end": 1.5,
                                "confidence": 0.9,
                                "speaker": 1,
                            },
                        ],
                    }
                ]
            }
        ]
    },
}


def test_language_mapping() -> None:
    assert deepgram_language("hi-IN") == "hi"
    assert deepgram_language("en-IN") == "en-IN"
    assert deepgram_language("multi") == "multi"


@respx.mock
async def test_batch_transcribe_with_diarization_and_bias() -> None:
    route = respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(200, json=LISTEN)
    )
    stt = DeepgramSTT(SETTINGS, retry_delay=0)
    result = await stt.transcribe(make_wav(2.0), "hi-IN", diarize=True, bias_words=["EMI", "Kotak"])
    request = route.calls.last.request
    query = parse_qs(request.url.query.decode())
    assert request.headers["authorization"] == "Token dg-test"
    assert request.headers["content-type"] == "audio/wav"
    assert query["model"] == ["nova-3"] and query["language"] == ["hi"]
    assert query["diarize"] == ["true"] and query["keyterm"] == ["EMI", "Kotak"]
    assert result.text == "hello there friend" and result.confidence == pytest.approx(0.97)
    assert [w.text for w in result.words] == ["Hello", "there", "friend"]
    assert result.words[0].confidence == pytest.approx(0.99)
    assert [(s.speaker, s.text) for s in result.segments] == [("0", "Hello there"), ("1", "friend")]
    assert result.usage.audio_seconds == 2.0
    assert result.usage.est_cost == pytest.approx(0.02)
    await stt.aclose()


@respx.mock
async def test_batch_without_diarization_has_one_segment() -> None:
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(200, json=LISTEN)
    )
    result = await DeepgramSTT(SETTINGS, retry_delay=0).transcribe(make_wav(2.0), "en-IN")
    assert len(result.segments) == 1 and result.segments[0].end_s == 1.5


@respx.mock
async def test_batch_empty_transcript_and_bad_shape() -> None:
    body = {"results": {"channels": [{"alternatives": [{"transcript": "", "words": []}]}]}}
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(200, json=body)
    )
    stt = DeepgramSTT(SETTINGS, retry_delay=0)
    result = await stt.transcribe(make_wav(1.0), "hi-IN")
    assert result.text == "" and result.segments == [] and result.duration_s == 1.0
    respx.post("https://api.deepgram.com/v1/listen").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(SpeechPermanentError, match="unexpected"):
        await stt.transcribe(make_wav(1.0), "hi-IN")


@respx.mock
async def test_errors_map_to_typed_exceptions() -> None:
    stt = DeepgramSTT(SETTINGS, retry_delay=0)
    respx.post("https://api.deepgram.com/v1/listen").mock(
        return_value=httpx.Response(401, text="no")
    )
    with pytest.raises(SpeechPermanentError):
        await stt.transcribe(make_wav(), "hi-IN")
    respx.post("https://api.deepgram.com/v1/listen").mock(return_value=httpx.Response(503))
    with pytest.raises(SpeechRetryableError):
        await stt.transcribe(make_wav(), "hi-IN")


@respx.mock
async def test_tts_returns_wav_at_requested_rate() -> None:
    wav = pcm_to_wav(b"\x01\x00" * 24000, 24000)
    route = respx.post("https://api.deepgram.com/v1/speak").mock(
        return_value=httpx.Response(200, content=wav)
    )
    tts = DeepgramTTS(SETTINGS, retry_delay=0)
    result = await tts.synthesize("namaste", None, "en-US", sample_rate=24000)
    query = parse_qs(route.calls.last.request.url.query.decode())
    assert query == {
        "model": ["aura-2-thalia-en"],
        "encoding": ["linear16"],
        "container": ["wav"],
        "sample_rate": ["24000"],
    }
    assert json.loads(route.calls.last.request.content) == {"text": "namaste"}
    assert result.sample_rate == 24000 and result.duration_s == pytest.approx(1.0)
    assert result.usage.characters == 7 and result.usage.est_cost == pytest.approx(0.021)
    assert result.voice == "aura-2-thalia-en"
    with pytest.raises(UnsupportedCapabilityError):
        await tts.synthesize("x", None, "en-US", speed=1.2)


@respx.mock
async def test_list_voices_filters_by_language() -> None:
    body = {
        "stt": [],
        "tts": [
            {"name": "zeus", "canonical_name": "aura-2-zeus-en", "languages": ["en", "en-US"]},
            {"name": "celeste", "canonical_name": "aura-2-celeste-es", "languages": ["es"]},
        ],
    }
    respx.get("https://api.deepgram.com/v1/models").mock(
        return_value=httpx.Response(200, json=body)
    )
    tts = DeepgramTTS(SETTINGS, retry_delay=0)
    assert len(await tts.list_voices()) == 2
    assert [v.id for v in await tts.list_voices("en-IN")] == ["aura-2-zeus-en"]
    assert await tts.list_voices("hi-IN") == []


async def _chunks() -> AsyncIterator[bytes]:
    for _ in range(3):
        yield b"\x00\x01" * 160


async def test_streaming_against_local_websocket_server() -> None:
    received: list[object] = []
    seen_path: list[str] = []
    seen_auth: list[str | None] = []

    async def handler(ws: ServerConnection) -> None:
        seen_path.append(ws.request.path if ws.request else "")
        seen_auth.append(ws.request.headers.get("Authorization") if ws.request else None)
        async for message in ws:
            received.append(message)
            if isinstance(message, str) and json.loads(message)["type"] == "CloseStream":
                break
        await ws.send(b"binary-ignored")
        await ws.send(json.dumps({"type": "Metadata"}))
        await ws.send(
            json.dumps(
                {
                    "type": "Results",
                    "is_final": False,
                    "start": 0.0,
                    "duration": 0.5,
                    "channel": {"alternatives": [{"transcript": "hel", "confidence": 0.5}]},
                }
            )
        )
        await ws.send(
            json.dumps(
                {
                    "type": "Results",
                    "is_final": True,
                    "start": 0.0,
                    "duration": 1.0,
                    "channel": {"alternatives": [{"transcript": "hello", "confidence": 0.9}]},
                }
            )
        )
        await ws.send(
            json.dumps(
                {
                    "type": "Results",
                    "is_final": True,
                    "channel": {"alternatives": [{"transcript": ""}]},
                }
            )
        )
        await ws.close()

    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        stt = DeepgramSTT(SETTINGS, ws_url=f"ws://127.0.0.1:{port}")
        events = [e async for e in stt.transcribe_stream(_chunks(), "hi-IN", sample_rate=16000)]
    assert [(e.text, e.is_final) for e in events] == [("hel", False), ("hello", True)]
    assert events[1].end_s == pytest.approx(1.0) and events[1].confidence == pytest.approx(0.9)
    assert received[:3] == [b"\x00\x01" * 160] * 3
    assert json.loads(str(received[3])) == {"type": "CloseStream"}
    assert "encoding=linear16" in seen_path[0] and "language=hi" in seen_path[0]
    assert seen_auth == ["Token dg-test"]


async def test_streaming_connection_failure_is_retryable() -> None:
    stt = DeepgramSTT(SETTINGS, ws_url="ws://127.0.0.1:1")
    with pytest.raises(SpeechRetryableError):
        _ = [e async for e in stt.transcribe_stream(_chunks(), "hi-IN")]


async def test_streaming_rejected_handshake_is_permanent() -> None:
    async def reject(connection: ServerConnection, request: object) -> object:
        return connection.respond(401, "nope")

    async def handler(ws: ServerConnection) -> None:  # pragma: no cover - never reached
        await ws.close()

    async with serve(handler, "127.0.0.1", 0, process_request=reject) as server:  # type: ignore[arg-type]
        port = server.sockets[0].getsockname()[1]
        stt = DeepgramSTT(SETTINGS, ws_url=f"ws://127.0.0.1:{port}")
        with pytest.raises(SpeechPermanentError, match="401"):
            _ = [e async for e in stt.transcribe_stream(_chunks(), "hi-IN")]
