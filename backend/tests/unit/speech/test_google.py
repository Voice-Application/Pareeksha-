"""Google Cloud adapter with HTTP mocked and the OAuth token supplied by a stub provider."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from pareeksha.speech import SpeechConfigError, SpeechPermanentError, UnsupportedCapabilityError
from pareeksha.speech.providers import google as google_mod
from pareeksha.speech.providers.google import GoogleSTT, GoogleTTS, service_account_token_provider
from pareeksha.speech.wav import pcm_to_wav

from .conftest import make_settings, make_wav

SETTINGS = make_settings(
    google_application_credentials_json="{}",
    google_tts_voice="hi-IN-Neural2-A",
    cost_google_stt_per_min=1.44,
    cost_google_tts_per_1k_chars=16.0,
)
STT_URL = "https://us-central1-speech.googleapis.com/v2/projects/proj-1/locations/us-central1/recognizers/_:recognize"


def stt() -> GoogleSTT:
    return GoogleSTT(SETTINGS, token_provider=lambda: "tok", project_id="proj-1", retry_delay=0)


def tts() -> GoogleTTS:
    return GoogleTTS(SETTINGS, token_provider=lambda: "tok", project_id="proj-1", retry_delay=0)


RECOGNIZE = {
    "results": [
        {
            "alternatives": [
                {
                    "transcript": "namaste dost",
                    "confidence": 0.9,
                    "words": [
                        {
                            "startOffset": "0s",
                            "endOffset": "0.600s",
                            "word": "namaste",
                            "confidence": 0.95,
                            "speakerLabel": "1",
                        },
                        {
                            "startOffset": "0.800s",
                            "endOffset": "1.200s",
                            "word": "dost",
                            "confidence": 0.85,
                            "speakerLabel": "1",
                        },
                    ],
                }
            ],
            "resultEndOffset": "1.200s",
            "languageCode": "hi-in",
        },
        {"alternatives": []},
        {"alternatives": [{"transcript": " phir milte hain "}], "resultEndOffset": "3s"},
    ],
    "metadata": {"totalBilledDuration": "5s"},
}


@respx.mock
async def test_recognize_request_and_mapping() -> None:
    route = respx.post(STT_URL).mock(return_value=httpx.Response(200, json=RECOGNIZE))
    result = await stt().transcribe(
        make_wav(4.0), "hi-IN", diarize=True, num_speakers=2, bias_words=["EMI"]
    )
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer tok"
    body = json.loads(request.content)
    cfg = body["config"]
    assert cfg["languageCodes"] == ["hi-IN"] and cfg["model"] == "chirp_2"
    assert cfg["features"]["enableWordConfidence"] and cfg["features"]["enableWordTimeOffsets"]
    assert cfg["features"]["diarizationConfig"] == {"minSpeakerCount": 1, "maxSpeakerCount": 2}
    phrases = cfg["adaptation"]["phraseSets"][0]["inlinePhraseSet"]["phrases"]
    assert phrases == [{"value": "EMI", "boost": 10}]
    assert base64.b64decode(body["content"])[:4] == b"RIFF"
    assert result.text == "namaste dost phir milte hain" and result.language == "hi-in"
    assert [w.text for w in result.words] == ["namaste", "dost"]
    assert result.words[0].start_s == 0.0 and result.words[0].end_s == pytest.approx(0.6)
    assert result.words[0].confidence == pytest.approx(0.95) and result.words[0].speaker == "1"
    assert [s.end_s for s in result.segments] == [pytest.approx(1.2), pytest.approx(3.0)]
    assert result.confidence == pytest.approx(0.9)
    assert result.usage.audio_seconds == 5.0
    assert result.usage.est_cost == pytest.approx(0.12)


@respx.mock
async def test_global_location_uses_global_host_and_plain_config() -> None:
    settings = make_settings(
        google_application_credentials_json="{}", google_speech_location="global"
    )
    route = respx.post(
        "https://speech.googleapis.com/v2/projects/p/locations/global/recognizers/_:recognize"
    ).mock(return_value=httpx.Response(200, json={}))
    provider = GoogleSTT(settings, token_provider=lambda: "t", project_id="p", retry_delay=0)
    result = await provider.transcribe(make_wav(1.0), "en-IN")
    cfg = json.loads(route.calls.last.request.content)["config"]
    assert "diarizationConfig" not in cfg["features"] and "adaptation" not in cfg
    assert result.text == "" and result.usage.audio_seconds == 1.0 and result.usage.est_cost is None


async def test_sync_limit_is_enforced() -> None:
    with pytest.raises(UnsupportedCapabilityError, match="60 s"):
        await stt().transcribe(make_wav(61.0, rate=8000), "hi-IN")


@respx.mock
async def test_tts_decodes_base64_wav() -> None:
    wav = pcm_to_wav(b"\x01\x00" * 16000, 16000)
    route = respx.post("https://texttospeech.googleapis.com/v1/text:synthesize").mock(
        return_value=httpx.Response(200, json={"audioContent": base64.b64encode(wav).decode()})
    )
    result = await tts().synthesize("namaste", None, "hi-IN", sample_rate=16000, speed=0.9)
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "input": {"text": "namaste"},
        "voice": {"languageCode": "hi-IN", "name": "hi-IN-Neural2-A"},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 16000, "speakingRate": 0.9},
    }
    assert route.calls.last.request.headers["x-goog-user-project"] == "proj-1"
    assert result.audio == wav and result.sample_rate == 16000
    assert result.usage.est_cost == pytest.approx(0.112)


@respx.mock
async def test_tts_errors() -> None:
    provider = tts()
    respx.post("https://texttospeech.googleapis.com/v1/text:synthesize").mock(
        return_value=httpx.Response(200, json={})
    )
    with pytest.raises(SpeechPermanentError, match="unexpected"):
        await provider.synthesize("x", "v", "hi-IN")
    respx.post("https://texttospeech.googleapis.com/v1/text:synthesize").mock(
        return_value=httpx.Response(200, json={"audioContent": "***"})
    )
    with pytest.raises(SpeechPermanentError):
        await provider.synthesize("x", "v", "hi-IN")
    with pytest.raises(SpeechPermanentError, match="voice name"):
        await GoogleTTS(
            make_settings(google_application_credentials_json="{}"),
            token_provider=lambda: "t",
            project_id="p",
        ).synthesize("x", None, "hi-IN")


@respx.mock
async def test_list_voices() -> None:
    route = respx.get("https://texttospeech.googleapis.com/v1/voices").mock(
        return_value=httpx.Response(
            200,
            json={
                "voices": [
                    {"name": "hi-IN-Neural2-A", "languageCodes": ["hi-IN"], "ssmlGender": "FEMALE"},
                    {"name": "x", "languageCodes": []},
                ]
            },
        )
    )
    voices = await tts().list_voices("hi-IN")
    assert route.calls.last.request.url.params["languageCode"] == "hi-IN"
    assert voices[0].gender == "female" and voices[1].gender is None
    await tts().list_voices()
    assert "languageCode" not in route.calls.last.request.url.params


def _service_account_json() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "proj-from-key",
            "private_key_id": "k1",
            "private_key": pem,
            "client_email": "svc@proj-from-key.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def test_service_account_credentials_parse_and_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    from google.oauth2 import service_account

    def fake_refresh(self: Any, request: Any) -> None:
        self.token = "minted"
        self.expiry = None

    monkeypatch.setattr(service_account.Credentials, "refresh", fake_refresh)
    get_token, project = service_account_token_provider(_service_account_json())
    assert project == "proj-from-key" and get_token() == "minted"
    adapter = GoogleTTS(
        make_settings(google_application_credentials_json=_service_account_json()), retry_delay=0
    )
    assert adapter.project_id == "proj-from-key"


def test_invalid_credentials_json_is_a_config_error() -> None:
    with pytest.raises(SpeechConfigError, match="not valid JSON"):
        service_account_token_provider("{nope")
    assert google_mod.SCOPES == ["https://www.googleapis.com/auth/cloud-platform"]
