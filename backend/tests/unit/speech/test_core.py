"""Interfaces, settings, retry policy, registry and status (no vendor specifics)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from pareeksha.api.auth import authenticate
from pareeksha.api.main import app
from pareeksha.speech import (
    SpeechConfigError,
    SpeechNoAudioError,
    SpeechPermanentError,
    SpeechProviderName,
    SpeechRetryableError,
    SpeechSelection,
    UnsupportedCapabilityError,
    get_stt_provider,
    get_tts_provider,
    provider_status,
)
from pareeksha.speech import http as speech_http
from pareeksha.speech.text import has_speakable_text
from pareeksha.speech.providers.deepgram import DeepgramSTT, DeepgramTTS
from pareeksha.speech.providers.elevenlabs import ElevenLabsSTT
from pareeksha.speech.providers.gnani import GnaniSTT, GnaniTTS
from pareeksha.speech.wav import pcm_to_wav, wav_info

from .conftest import make_settings

URL = "https://example.test/x"


def test_defaults_are_gnani() -> None:
    s = make_settings()
    assert s.stt_provider is SpeechProviderName.GNANI
    assert s.tts_provider is SpeechProviderName.GNANI


def test_env_selects_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "k")
    provider = get_stt_provider(settings=make_settings())
    assert isinstance(provider, DeepgramSTT)


def test_precedence_name_over_selection_over_env() -> None:
    s = make_settings(deepgram_api_key="k", elevenlabs_api_key="k", gnani_api_key="k")
    sel = SpeechSelection(stt=SpeechProviderName.ELEVENLABS)
    assert isinstance(get_stt_provider(selection=sel, settings=s), ElevenLabsSTT)
    assert isinstance(get_stt_provider("deepgram", selection=sel, settings=s), DeepgramSTT)
    assert isinstance(get_stt_provider(settings=s), GnaniSTT)
    assert isinstance(get_tts_provider(settings=s), GnaniTTS)
    assert isinstance(
        get_tts_provider(selection=SpeechSelection(tts=SpeechProviderName.DEEPGRAM), settings=s),
        DeepgramTTS,
    )


def test_selection_rejects_unknown_provider_and_extra_fields() -> None:
    with pytest.raises(ValueError):
        SpeechSelection(stt="nope")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        SpeechSelection(llm="x")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("name", "missing"),
    [
        ("gnani", ["GNANI_API_KEY"]),
        ("google", ["GOOGLE_APPLICATION_CREDENTIALS_JSON"]),
        ("azure", ["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"]),
        ("elevenlabs", ["ELEVENLABS_API_KEY"]),
        ("deepgram", ["DEEPGRAM_API_KEY"]),
    ],
)
def test_unconfigured_provider_raises_config_error(name: str, missing: list[str]) -> None:
    s = make_settings()
    assert s.missing_env(SpeechProviderName(name)) == missing
    with pytest.raises(SpeechConfigError, match=missing[0]):
        get_stt_provider(name, settings=s)
    with pytest.raises(SpeechConfigError):
        get_tts_provider(name, settings=s)


def test_costs_use_provider_specific_rates() -> None:
    s = make_settings(
        cost_tts_per_1k_chars=2,
        cost_stt_rest_per_min=6,
        cost_stt_batch_per_min=3,
        cost_stt_stream_per_min=12,
        cost_deepgram_stt_per_min=0.6,
        cost_deepgram_tts_per_1k_chars=4,
    )
    g, d = SpeechProviderName.GNANI, SpeechProviderName.DEEPGRAM
    assert s.stt_cost(g, 30, "stt_rest") == pytest.approx(3)
    assert s.stt_cost(g, 30, "stt_stream") == pytest.approx(6)
    assert s.stt_cost(g, 30, "stt_batch") == pytest.approx(1.5)
    assert s.tts_cost(g, 500) == pytest.approx(1)
    assert s.stt_cost(d, 60) == pytest.approx(0.6)
    assert s.tts_cost(d, 250) == pytest.approx(1)
    assert s.stt_cost(SpeechProviderName.AZURE, 60) is None
    assert s.tts_cost(SpeechProviderName.AZURE, 60) is None


def test_provider_status_reports_presence_without_secrets() -> None:
    s = make_settings(deepgram_api_key="sekrit-value", tts_provider="deepgram")
    rows = {r.name.value: r for r in provider_status(s)}
    assert set(rows) == {"gnani", "google", "azure", "elevenlabs", "deepgram"}
    assert rows["deepgram"].configured and rows["deepgram"].missing_env == []
    assert rows["deepgram"].tts_default and not rows["deepgram"].stt_default
    assert rows["gnani"].stt_default and not rows["gnani"].configured
    assert rows["azure"].missing_env == ["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"]
    assert rows["deepgram"].stt.streaming and not rows["elevenlabs"].stt.streaming
    assert "sekrit-value" not in "".join(r.model_dump_json() for r in rows.values())


def test_api_route_requires_auth_and_lists_providers() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/speech/providers").status_code == 401
    # API-01's key lookup is DB-backed (covered in tests/db); here only the payload matters.
    app.dependency_overrides[authenticate] = lambda: None
    try:
        response = client.get(
            "/api/v1/speech/providers", headers={"Authorization": "Bearer pk_live_t"}
        )
    finally:
        app.dependency_overrides.pop(authenticate, None)
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["name"] for i in items] == ["gnani", "google", "azure", "elevenlabs", "deepgram"]
    assert all({"configured", "missing_env", "stt", "tts"} <= set(i) for i in items)


async def test_default_stream_is_unsupported() -> None:
    provider = ElevenLabsSTT(make_settings(elevenlabs_api_key="k"))
    with pytest.raises(UnsupportedCapabilityError):
        provider.transcribe_stream(_empty(), "hi-IN")
    await provider.aclose()


async def _empty() -> AsyncIterator[bytes]:
    return
    yield b""


def test_wav_helpers_round_trip() -> None:
    wav = pcm_to_wav(b"\x00\x00" * 8000, 8000)
    assert wav_info(wav) == (8000, 1.0)


@respx.mock
async def test_retries_5xx_then_succeeds() -> None:
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(429, headers={"retry-after": "1"}),
            httpx.Response(200),
        ]
    )
    async with httpx.AsyncClient() as client:
        response = await speech_http.send(client, "GET", URL, retry_delay=0)
    assert response.status_code == 200 and route.call_count == 3


@respx.mock
async def test_gives_up_with_retryable_error_and_retry_after() -> None:
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"retry-after": "7"}))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SpeechRetryableError) as caught:
            await speech_http.send(client, "GET", URL, retry_delay=0)
    assert caught.value.retry_after_s == 7.0


@respx.mock
async def test_timeouts_are_retryable_and_4xx_is_not() -> None:
    route = respx.get(URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SpeechRetryableError, match="ConnectTimeout"):
            await speech_http.send(client, "GET", URL, retry_delay=0)
        assert route.call_count == 3
        respx.get(URL).mock(return_value=httpx.Response(401, text="bad key"))
        with pytest.raises(SpeechPermanentError, match="401"):
            await speech_http.send(client, "GET", URL, retry_delay=0)


@respx.mock
async def test_no_audio_generated_is_permanent_and_not_retried() -> None:
    route = respx.post(URL).mock(
        return_value=httpx.Response(500, text='{"detail": "No audio generated during synthesis"}')
    )
    async with httpx.AsyncClient() as client:
        with pytest.raises(SpeechNoAudioError, match="No audio generated"):
            await speech_http.send(client, "POST", URL, retry_delay=0)
    assert route.call_count == 1
    assert issubclass(SpeechNoAudioError, SpeechPermanentError)


@respx.mock
async def test_other_500s_still_retry() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(500, text="internal error"))
    async with httpx.AsyncClient() as client:
        with pytest.raises(SpeechRetryableError):
            await speech_http.send(client, "POST", URL, retry_delay=0)
    assert route.call_count == 3


@pytest.mark.parametrize("text", ["...", "…", "  - ? ! ", "।", "", "\u2026 \u2026"])
def test_punctuation_only_text_is_not_speakable(text: str) -> None:
    assert not has_speakable_text(text)


@pytest.mark.parametrize("text", ["ok", "42", "ಹೌದು", "हाँ...", "ಕ್ಷಮಿಸಿ", "... yes"])
def test_text_with_words_is_speakable(text: str) -> None:
    assert has_speakable_text(text)


def test_wav_info_streamed_header_placeholder_size() -> None:
    """Streamed WAV (Deepgram TTS) has data size 0xFFFFFFFF; duration uses the bytes present."""
    import struct

    from pareeksha.speech.wav import pcm_to_wav, wav_info

    wav = bytearray(pcm_to_wav(b"\x00\x00" * 16000, 16000))
    wav[40:44] = struct.pack("<I", 0xFFFFFFFF)
    assert wav_info(bytes(wav)) == (16000, 1.0)
