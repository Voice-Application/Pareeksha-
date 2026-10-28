"""ElevenLabs adapter with HTTP mocked."""

from __future__ import annotations

import json
import math

import httpx
import pytest
import respx

from pareeksha.speech import SpeechPermanentError, UnsupportedCapabilityError
from pareeksha.speech.providers.elevenlabs import ElevenLabsSTT, ElevenLabsTTS

from .conftest import make_settings, make_wav

SETTINGS = make_settings(
    elevenlabs_api_key="el-test",
    elevenlabs_tts_voice="voice123",
    cost_elevenlabs_stt_per_min=6.0,
    cost_elevenlabs_tts_per_1k_chars=2.0,
)
STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

SCRIBE = {
    "language_code": "hin",
    "language_probability": 0.99,
    "text": "namaste dost",
    "words": [
        {
            "text": "namaste",
            "start": 0.0,
            "end": 0.6,
            "type": "word",
            "speaker_id": "speaker_0",
            "logprob": math.log(0.9),
        },
        {"text": " ", "start": 0.6, "end": 0.7, "type": "spacing", "speaker_id": "speaker_0"},
        {
            "text": "dost",
            "start": 0.8,
            "end": 1.2,
            "type": "word",
            "speaker_id": "speaker_1",
            "logprob": 0.0,
        },
        {"text": "(laughter)", "start": 1.2, "end": 1.4, "type": "audio_event"},
    ],
}


@respx.mock
async def test_scribe_transcribe_maps_words_and_speakers() -> None:
    route = respx.post(STT_URL).mock(return_value=httpx.Response(200, json=SCRIBE))
    stt = ElevenLabsSTT(SETTINGS, retry_delay=0)
    result = await stt.transcribe(make_wav(2.0), "hi-IN", diarize=True, num_speakers=2)
    request = route.calls.last.request
    body = request.content
    assert request.headers["xi-api-key"] == "el-test"
    for part in (
        b'name="model_id"\r\n\r\nscribe_v1',
        b'name="language_code"\r\n\r\nhi',
        b'name="diarize"\r\n\r\ntrue',
        b'name="num_speakers"\r\n\r\n2',
    ):
        assert part in body
    assert result.text == "namaste dost" and result.language == "hin"
    assert [w.text for w in result.words] == ["namaste", "dost"]
    assert result.words[0].confidence == pytest.approx(0.9)
    assert result.words[1].confidence == pytest.approx(1.0)
    assert [(s.speaker, s.text) for s in result.segments] == [
        ("speaker_0", "namaste"),
        ("speaker_1", "dost"),
    ]
    assert result.duration_s == 2.0
    assert result.usage.est_cost == pytest.approx(0.2)


@respx.mock
async def test_scribe_without_diarization_one_segment_and_errors() -> None:
    respx.post(STT_URL).mock(return_value=httpx.Response(200, json=SCRIBE))
    stt = ElevenLabsSTT(SETTINGS, retry_delay=0)
    result = await stt.transcribe(make_wav(2.0), "hi-IN")
    assert len(result.segments) == 1 and b"" == b""
    with pytest.raises(UnsupportedCapabilityError):
        await stt.transcribe(make_wav(), "hi-IN", bias_words=["x"])
    respx.post(STT_URL).mock(return_value=httpx.Response(200, json={"words": []}))
    with pytest.raises(SpeechPermanentError, match="no 'text'"):
        await stt.transcribe(make_wav(), "hi-IN")
    respx.post(STT_URL).mock(return_value=httpx.Response(200, json={"text": "", "words": []}))
    empty = await stt.transcribe(make_wav(1.0), "hi-IN")
    assert empty.segments == [] and empty.confidence is None and empty.language == "hi-IN"


@respx.mock
async def test_tts_pcm_wrapped_as_wav() -> None:
    pcm = b"\x01\x00" * 8000
    route = respx.post("https://api.elevenlabs.io/v1/text-to-speech/voice123").mock(
        return_value=httpx.Response(200, content=pcm)
    )
    tts = ElevenLabsTTS(SETTINGS, retry_delay=0)
    result = await tts.synthesize("namaste", None, "hi-IN", sample_rate=8000, speed=1.1)
    request = route.calls.last.request
    assert request.url.params["output_format"] == "pcm_8000"
    assert json.loads(request.content) == {
        "text": "namaste",
        "model_id": "eleven_multilingual_v2",
        "language_code": "hi",
        "voice_settings": {"speed": 1.1},
    }
    assert result.audio[:4] == b"RIFF" and result.sample_rate == 8000
    assert result.duration_s == pytest.approx(1.0)
    assert result.usage.est_cost == pytest.approx(0.014)


async def test_tts_input_validation() -> None:
    tts = ElevenLabsTTS(make_settings(elevenlabs_api_key="k"), retry_delay=0)
    with pytest.raises(SpeechPermanentError, match="voice id"):
        await tts.synthesize("x", None, "hi-IN")
    with pytest.raises(SpeechPermanentError, match="supports"):
        await tts.synthesize("x", "v", "hi-IN", sample_rate=12345)


@respx.mock
async def test_list_voices_filters_verified_languages() -> None:
    body = {
        "voices": [
            {
                "voice_id": "a",
                "name": "Asha",
                "labels": {"gender": "female"},
                "verified_languages": [{"language": "hi"}, {"language": "en"}],
            },
            {"voice_id": "b", "name": "Bo", "verified_languages": [{"language": "fr"}]},
            {"voice_id": "c", "name": "Unlabelled"},
        ]
    }
    respx.get("https://api.elevenlabs.io/v1/voices").mock(
        return_value=httpx.Response(200, json=body)
    )
    tts = ElevenLabsTTS(SETTINGS, retry_delay=0)
    assert len(await tts.list_voices()) == 3
    filtered = await tts.list_voices("hi-IN")
    assert [v.id for v in filtered] == ["a", "c"] and filtered[0].gender == "female"
