"""Azure AI Speech adapter with HTTP mocked."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from pareeksha.speech import SpeechPermanentError
from pareeksha.speech.providers.azure import AzureSTT, AzureTTS
from pareeksha.speech.wav import pcm_to_wav

from .conftest import make_settings, make_wav

SETTINGS = make_settings(
    azure_speech_key="az-test",
    azure_speech_region="centralindia",
    azure_tts_voice="hi-IN-SwaraNeural",
    cost_azure_stt_per_min=1.2,
    cost_azure_tts_per_1k_chars=16.0,
)
STT_URL = "https://centralindia.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe"
TTS_BASE = "https://centralindia.tts.speech.microsoft.com"

FAST = {
    "durationMilliseconds": 3000,
    "combinedPhrases": [{"text": "Namaste. Haan boliye."}],
    "phrases": [
        {
            "speaker": 1,
            "offsetMilliseconds": 500,
            "durationMilliseconds": 800,
            "text": "Namaste.",
            "words": [{"text": "Namaste.", "offsetMilliseconds": 500, "durationMilliseconds": 800}],
            "locale": "hi-IN",
            "confidence": 0.91,
        },
        {
            "speaker": 2,
            "offsetMilliseconds": 1600,
            "durationMilliseconds": 900,
            "text": "Haan boliye.",
            "words": [
                {"text": "Haan", "offsetMilliseconds": 1600, "durationMilliseconds": 400},
                {"text": "boliye.", "offsetMilliseconds": 2000, "durationMilliseconds": 500},
            ],
            "locale": "hi-IN",
        },
    ],
}


@respx.mock
async def test_fast_transcription_request_and_mapping() -> None:
    route = respx.post(STT_URL).mock(return_value=httpx.Response(200, json=FAST))
    stt = AzureSTT(SETTINGS, retry_delay=0)
    result = await stt.transcribe(
        make_wav(3.0), "hi-IN", diarize=True, num_speakers=3, bias_words=["EMI"]
    )
    request = route.calls.last.request
    assert request.url.params["api-version"] == "2025-10-15"
    assert request.headers["ocp-apim-subscription-key"] == "az-test"
    marker = b'name="definition"\r\n\r\n'
    raw = request.content.split(marker)[1].split(b"\r\n--")[0]
    assert json.loads(raw) == {
        "locales": ["hi-IN"],
        "diarization": {"enabled": True, "maxSpeakers": 3},
        "phraseList": {"phrases": ["EMI"]},
    }
    assert result.text == "Namaste. Haan boliye." and result.language == "hi-IN"
    assert result.duration_s == 3.0 and result.confidence == pytest.approx(0.91)
    assert [(s.speaker, s.start_s, s.end_s) for s in result.segments] == [
        ("1", 0.5, 1.3),
        ("2", 1.6, 2.5),
    ]
    assert [w.text for w in result.words] == ["Namaste.", "Haan", "boliye."]
    assert all(w.confidence is None for w in result.words)
    assert result.usage.est_cost == pytest.approx(0.06)


@respx.mock
async def test_transcription_without_options_and_bad_response() -> None:
    body = {
        "durationMilliseconds": 0,
        "phrases": [{"offsetMilliseconds": 0, "durationMilliseconds": 500, "text": "ok"}],
    }
    route = respx.post(STT_URL).mock(return_value=httpx.Response(200, json=body))
    stt = AzureSTT(SETTINGS, retry_delay=0)
    result = await stt.transcribe(make_wav(1.0), "hi-IN")
    assert result.text == "ok" and result.duration_s == 1.0 and result.language == "hi-IN"
    assert b"diarization" not in route.calls.last.request.content
    respx.post(STT_URL).mock(return_value=httpx.Response(200, json={"durationMilliseconds": 5}))
    with pytest.raises(SpeechPermanentError, match="no phrases"):
        await stt.transcribe(make_wav(1.0), "hi-IN")


@respx.mock
async def test_tts_ssml_and_headers() -> None:
    wav = pcm_to_wav(b"\x01\x00" * 24000, 24000)
    route = respx.post(f"{TTS_BASE}/cognitiveservices/v1").mock(
        return_value=httpx.Response(200, content=wav)
    )
    tts = AzureTTS(SETTINGS, retry_delay=0)
    result = await tts.synthesize("Tom & <Jerry>", None, "hi-IN", sample_rate=24000, speed=1.2)
    request = route.calls.last.request
    assert request.headers["x-microsoft-outputformat"] == "riff-24khz-16bit-mono-pcm"
    assert request.headers["content-type"] == "application/ssml+xml"
    assert request.headers["ocp-apim-subscription-key"] == "az-test"
    ssml = request.content.decode()
    assert "Tom &amp; &lt;Jerry&gt;" in ssml and "hi-IN-SwaraNeural" in ssml
    assert 'rate="1.2"' in ssml and 'xml:lang="hi-IN"' in ssml
    assert result.sample_rate == 24000 and result.duration_s == pytest.approx(1.0)
    assert result.usage.est_cost == pytest.approx(16.0 * 13 / 1000)


async def test_tts_input_validation() -> None:
    tts = AzureTTS(make_settings(azure_speech_key="k", azure_speech_region="r"))
    with pytest.raises(SpeechPermanentError, match="voice name"):
        await tts.synthesize("x", None, "hi-IN")
    with pytest.raises(SpeechPermanentError, match="supports"):
        await tts.synthesize("x", "v", "hi-IN", sample_rate=11025)


@respx.mock
async def test_list_voices_filters_by_locale() -> None:
    body = [
        {
            "ShortName": "hi-IN-SwaraNeural",
            "LocalName": "Swara",
            "Locale": "hi-IN",
            "Gender": "Female",
        },
        {"ShortName": "kn-IN-SapnaNeural", "Locale": "kn-IN", "Gender": "Female"},
    ]
    respx.get(f"{TTS_BASE}/cognitiveservices/voices/list").mock(
        return_value=httpx.Response(200, json=body)
    )
    tts = AzureTTS(SETTINGS, retry_delay=0)
    assert len(await tts.list_voices()) == 2
    only = await tts.list_voices("kn-in")
    assert [v.id for v in only] == ["kn-IN-SapnaNeural"] and only[0].name == "kn-IN-SapnaNeural"
