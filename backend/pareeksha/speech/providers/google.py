"""Google Cloud adapter: Speech-to-Text v2 ``recognize`` (REST) and Text-to-Speech v1 (REST).

Docs (checked 2026-10-24): https://cloud.google.com/speech-to-text/v2/docs/sync-recognize
(``POST .../recognizers/_:recognize`` with ``autoDecodingConfig``,
``features.enableWordTimeOffsets``,
``enableWordConfidence``, 60 s / 10 MB sync limit) and
https://cloud.google.com/text-to-speech/docs/reference/rest/v1/text/synthesize (LINEAR16 returns a
WAV in base64 ``audioContent``). Auth: service-account JSON in
``GOOGLE_APPLICATION_CREDENTIALS_JSON``
exchanged for a bearer token with ``google-auth``. Streaming STT is gRPC-only and not wired:
``streaming=False``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from pareeksha.speech.base import (
    SpeechConfigError,
    SpeechPermanentError,
    SpeechProviderName,
    SpeechUsage,
    STTCapabilities,
    STTProvider,
    SynthesisResult,
    Transcript,
    TranscriptSegment,
    TTSCapabilities,
    TTSProvider,
    UnsupportedCapabilityError,
    Voice,
    WordTiming,
)
from pareeksha.speech.config import SpeechSettings
from pareeksha.speech.providers._common import HTTPAdapter, clamp01, elapsed_ms
from pareeksha.speech.wav import wav_info

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
TokenProvider = Callable[[], str]


def service_account_token_provider(credentials_json: str) -> tuple[TokenProvider, str]:
    """Return ``(get_token, project_id)`` for a service-account key given as a JSON string."""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    try:
        info = json.loads(credentials_json)
    except json.JSONDecodeError as exc:
        raise SpeechConfigError("GOOGLE_APPLICATION_CREDENTIALS_JSON is not valid JSON") from exc
    creds = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
        info, scopes=SCOPES
    )

    def get_token() -> str:
        if not creds.valid:
            creds.refresh(Request())
        return str(creds.token)

    return get_token, str(info["project_id"])


def _seconds(value: str | None) -> float:
    """Google durations are strings like ``"1.240s"``."""
    return float(value.rstrip("s")) if value else 0.0


class _GoogleAuth(HTTPAdapter):
    def __init__(
        self,
        settings: SpeechSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        retry_delay: float = 1.0,
        token_provider: TokenProvider | None = None,
        project_id: str | None = None,
    ) -> None:
        super().__init__(settings, client=client, retry_delay=retry_delay)
        if token_provider is None:
            creds = str(self.settings.google_application_credentials_json)
            token_provider, from_key = service_account_token_provider(creds)
            project_id = project_id or from_key
        self._token = token_provider
        self.project_id = project_id or ""

    async def _auth_headers(self) -> dict[str, str]:
        token = await asyncio.to_thread(self._token)
        return {"Authorization": f"Bearer {token}", "x-goog-user-project": self.project_id}


class GoogleSTT(_GoogleAuth, STTProvider):
    provider = name = SpeechProviderName.GOOGLE
    capabilities = STTCapabilities(
        streaming=False,
        word_timings=True,
        word_confidence=True,
        diarization=True,  # model dependent: not every model (e.g. chirp_2) accepts it
        max_batch_seconds=60.0,
        languages_note="Chirp 2 (us-central1) lists Hindi, Tamil, Telugu, Kannada, Marathi, more; "
        "diarization availability depends on the model; pending real-key acceptance",
    )

    async def transcribe(
        self,
        wav: bytes,
        language: str,
        *,
        diarize: bool = False,
        num_speakers: int | None = None,
        bias_words: list[str] | None = None,
        denoise: bool = False,
    ) -> Transcript:
        if denoise:
            raise UnsupportedCapabilityError(
                "google has no denoise option (see STTCapabilities.denoise)"
            )
        _, wav_s = wav_info(wav)
        if wav_s > 60.0:
            raise UnsupportedCapabilityError(
                "google sync recognize is limited to 60 s; split the audio or use BatchRecognize"
            )
        s = self.settings
        features: dict[str, Any] = {"enableWordTimeOffsets": True, "enableWordConfidence": True}
        if diarize:
            n = num_speakers or 2
            features["diarizationConfig"] = {"minSpeakerCount": 1, "maxSpeakerCount": n}
        config: dict[str, Any] = {
            "autoDecodingConfig": {},
            "languageCodes": [language],
            "model": s.google_stt_model,
            "features": features,
        }
        if bias_words:
            config["adaptation"] = {
                "phraseSets": [
                    {
                        "inlinePhraseSet": {
                            "phrases": [{"value": w, "boost": 10} for w in bias_words]
                        }
                    }
                ]
            }
        loc = s.google_speech_location
        host = "speech.googleapis.com" if loc == "global" else f"{loc}-speech.googleapis.com"
        url = (
            f"https://{host}/v2/projects/{self.project_id}/locations/{loc}/recognizers/_:recognize"
        )
        t0 = time.monotonic()
        response = await self._send(
            "POST",
            url,
            headers=await self._auth_headers(),
            json={"config": config, "content": base64.b64encode(wav).decode()},
        )
        body: dict[str, Any] = response.json()
        words: list[WordTiming] = []
        segments: list[TranscriptSegment] = []
        texts: list[str] = []
        confs: list[float] = []
        reported_lang = language
        for r in body.get("results", []):
            alts = r.get("alternatives") or []
            if not alts:
                continue
            alt = alts[0]
            reported_lang = str(r.get("languageCode") or reported_lang)
            texts.append(alt.get("transcript", "").strip())
            rwords = [
                WordTiming(
                    text=w["word"],
                    start_s=_seconds(w.get("startOffset")),
                    end_s=_seconds(w.get("endOffset")),
                    confidence=clamp01(float(w["confidence"])) if "confidence" in w else None,
                    speaker=w.get("speakerLabel"),
                )
                for w in alt.get("words", [])
            ]
            words += rwords
            conf = clamp01(float(alt["confidence"])) if "confidence" in alt else None
            if conf is not None:
                confs.append(conf)
            end = _seconds(r.get("resultEndOffset")) or (rwords[-1].end_s if rwords else 0.0)
            segments.append(
                TranscriptSegment(
                    text=texts[-1],
                    start_s=rwords[0].start_s if rwords else 0.0,
                    end_s=end,
                    speaker=rwords[0].speaker if rwords else None,
                    confidence=conf,
                )
            )
        billed = _seconds(body.get("metadata", {}).get("totalBilledDuration")) or wav_s
        return Transcript(
            provider=self.name,
            model=s.google_stt_model,
            text=" ".join(t for t in texts if t),
            language=reported_lang,
            duration_s=wav_s,
            confidence=sum(confs) / len(confs) if confs else None,
            segments=segments,
            words=words,
            usage=SpeechUsage(
                provider=self.name,
                operation="stt_batch",
                audio_seconds=billed,
                latency_ms=elapsed_ms(t0),
                est_cost=s.stt_cost(self.name, billed),
            ),
        )


class GoogleTTS(_GoogleAuth, TTSProvider):
    provider = name = SpeechProviderName.GOOGLE
    capabilities = TTSCapabilities(
        sample_rates=(8000, 16000, 22050, 24000, 44100, 48000),
        voice_listing=True,
        speed_control=True,
        voices_per_language=True,
        languages_note="Voices per locale (e.g. hi-IN-Neural2-A); list with list_voices()",
    )

    async def synthesize(
        self,
        text: str,
        voice: str | None,
        language: str,
        *,
        sample_rate: int = 16000,
        speed: float = 1.0,
    ) -> SynthesisResult:
        voice_name = voice or self.settings.google_tts_voice
        if not voice_name:
            raise SpeechPermanentError("google TTS needs a voice name (arg or GOOGLE_TTS_VOICE)")
        t0 = time.monotonic()
        response = await self._send(
            "POST",
            "https://texttospeech.googleapis.com/v1/text:synthesize",
            headers=await self._auth_headers(),
            json={
                "input": {"text": text},
                "voice": {"languageCode": language, "name": voice_name},
                "audioConfig": {
                    "audioEncoding": "LINEAR16",
                    "sampleRateHertz": sample_rate,
                    "speakingRate": speed,
                },
            },
        )
        try:
            audio = base64.b64decode(response.json()["audioContent"], validate=True)
        except (KeyError, binascii.Error) as exc:
            raise SpeechPermanentError(f"unexpected Google TTS response: {exc!r}") from exc
        rate, secs = wav_info(audio)
        return SynthesisResult(
            provider=self.name,
            voice=voice_name,
            audio=audio,
            sample_rate=rate,
            duration_s=secs,
            usage=SpeechUsage(
                provider=self.name,
                operation="tts",
                audio_seconds=secs,
                characters=len(text),
                latency_ms=elapsed_ms(t0),
                est_cost=self.settings.tts_cost(self.name, len(text)),
            ),
        )

    async def list_voices(self, language: str | None = None) -> list[Voice]:
        response = await self._send(
            "GET",
            "https://texttospeech.googleapis.com/v1/voices",
            headers=await self._auth_headers(),
            params={"languageCode": language} if language else None,
        )
        return [
            Voice(
                id=v["name"],
                name=v["name"],
                languages=list(v.get("languageCodes", [])),
                gender=str(v["ssmlGender"]).lower() if "ssmlGender" in v else None,
            )
            for v in response.json().get("voices", [])
        ]
