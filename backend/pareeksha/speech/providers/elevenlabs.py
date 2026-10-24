"""ElevenLabs adapter: Scribe STT (REST) and text-to-speech (REST, PCM output).

Docs (checked 2026-10-24): https://elevenlabs.io/docs/api-reference/speech-to-text/convert
(multipart ``model_id``, ``language_code``, ``diarize``, ``num_speakers``, word timestamps),
https://elevenlabs.io/docs/api-reference/text-to-speech/convert (``output_format=pcm_<rate>``).
Auth header ``xi-api-key``. Streaming STT (realtime Scribe) is not wired: ``streaming=False``.
"""

from __future__ import annotations

import math
import time
from typing import Any

import httpx

from pareeksha.speech.base import (
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
from pareeksha.speech.wav import pcm_to_wav, wav_info

BASE_URL = "https://api.elevenlabs.io"
PCM_RATES = (8000, 16000, 22050, 24000, 44100)


def _iso_639_1(language: str) -> str:
    return language.split("-", 1)[0].lower()


class ElevenLabsSTT(HTTPAdapter, STTProvider):
    provider = name = SpeechProviderName.ELEVENLABS
    capabilities = STTCapabilities(
        streaming=False,
        word_timings=True,
        word_confidence=True,  # derived from the per-word logprob
        diarization=True,
        languages_note="Scribe covers ~99 languages incl. Hindi, Tamil, Telugu, Kannada "
        "per ElevenLabs docs; accuracy on the owner's data is pending real-key acceptance",
    )

    def __init__(
        self,
        settings: SpeechSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        retry_delay: float = 1.0,
        base_url: str = BASE_URL,
    ) -> None:
        super().__init__(settings, client=client, retry_delay=retry_delay)
        self._base_url = base_url

    async def transcribe(
        self,
        wav: bytes,
        language: str,
        *,
        diarize: bool = False,
        num_speakers: int | None = None,
        bias_words: list[str] | None = None,
    ) -> Transcript:
        if bias_words:
            raise UnsupportedCapabilityError("elevenlabs Scribe has no bias-word list")
        model = self.settings.elevenlabs_stt_model
        form: dict[str, str] = {
            "model_id": model,
            "language_code": _iso_639_1(language),
            "timestamps_granularity": "word",
            "tag_audio_events": "false",
            "diarize": "true" if diarize else "false",
        }
        if diarize and num_speakers:
            form["num_speakers"] = str(num_speakers)
        t0 = time.monotonic()
        response = await self._send(
            "POST",
            f"{self._base_url}/v1/speech-to-text",
            headers={"xi-api-key": str(self.settings.elevenlabs_api_key)},
            data=form,
            files={"file": ("audio.wav", wav, "audio/wav")},
        )
        body: dict[str, Any] = response.json()
        if "text" not in body:
            raise SpeechPermanentError("unexpected ElevenLabs STT response: no 'text'")
        words = [
            WordTiming(
                text=w["text"],
                start_s=float(w["start"]),
                end_s=float(w["end"]),
                confidence=clamp01(math.exp(float(w["logprob"]))) if "logprob" in w else None,
                speaker=w.get("speaker_id"),
            )
            for w in body.get("words", [])
            if w.get("type", "word") == "word"
        ]
        duration = words[-1].end_s if words else wav_info(wav)[1]
        _, wav_s = wav_info(wav)
        segments = _by_speaker(words) if diarize else []
        if not segments and words:
            segments = [
                TranscriptSegment(
                    text=body["text"], start_s=words[0].start_s, end_s=words[-1].end_s
                )
            ]
        confs = [w.confidence for w in words if w.confidence is not None]
        return Transcript(
            provider=self.name,
            model=model,
            text=body["text"],
            language=str(body.get("language_code") or language),
            duration_s=max(duration, wav_s),
            confidence=sum(confs) / len(confs) if confs else None,
            segments=segments,
            words=words,
            usage=SpeechUsage(
                provider=self.name,
                operation="stt_batch",
                audio_seconds=wav_s,
                latency_ms=elapsed_ms(t0),
                est_cost=self.settings.stt_cost(self.name, wav_s),
            ),
        )


def _by_speaker(words: list[WordTiming]) -> list[TranscriptSegment]:
    out: list[TranscriptSegment] = []
    group: list[WordTiming] = []
    for w in [*words, None]:
        if group and (w is None or w.speaker != group[0].speaker):
            out.append(
                TranscriptSegment(
                    text=" ".join(x.text for x in group),
                    start_s=group[0].start_s,
                    end_s=group[-1].end_s,
                    speaker=group[0].speaker,
                )
            )
            group = []
        if w is not None:
            group.append(w)
    return out


class ElevenLabsTTS(HTTPAdapter, TTSProvider):
    provider = name = SpeechProviderName.ELEVENLABS
    capabilities = TTSCapabilities(
        sample_rates=PCM_RATES,
        voice_listing=True,
        speed_control=True,
        languages_note="eleven_multilingual_v2 / flash v2.5 speak Hindi, Tamil and more; "
        "Kannada, Telugu etc. depend on the model and are pending real-key acceptance",
    )

    def __init__(
        self,
        settings: SpeechSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        retry_delay: float = 1.0,
        base_url: str = BASE_URL,
    ) -> None:
        super().__init__(settings, client=client, retry_delay=retry_delay)
        self._base_url = base_url

    async def synthesize(
        self,
        text: str,
        voice: str | None,
        language: str,
        *,
        sample_rate: int = 16000,
        speed: float = 1.0,
    ) -> SynthesisResult:
        voice_id = voice or self.settings.elevenlabs_tts_voice
        if not voice_id:
            raise SpeechPermanentError(
                "elevenlabs TTS needs a voice id (arg or ELEVENLABS_TTS_VOICE)"
            )
        if sample_rate not in PCM_RATES:
            raise SpeechPermanentError(
                f"elevenlabs PCM output supports {PCM_RATES}, not {sample_rate}"
            )
        payload: dict[str, Any] = {
            "text": text,
            "model_id": self.settings.elevenlabs_tts_model,
            "language_code": _iso_639_1(language),
        }
        if speed != 1.0:
            payload["voice_settings"] = {"speed": speed}
        t0 = time.monotonic()
        response = await self._send(
            "POST",
            f"{self._base_url}/v1/text-to-speech/{voice_id}",
            params={"output_format": f"pcm_{sample_rate}"},
            headers={"xi-api-key": str(self.settings.elevenlabs_api_key)},
            json=payload,
        )
        audio = pcm_to_wav(response.content, sample_rate)
        secs = wav_info(audio)[1]
        return SynthesisResult(
            provider=self.name,
            voice=voice_id,
            audio=audio,
            sample_rate=sample_rate,
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
            f"{self._base_url}/v1/voices",
            headers={"xi-api-key": str(self.settings.elevenlabs_api_key)},
        )
        voices: list[Voice] = []
        for v in response.json().get("voices", []):
            langs = [
                str(x["language"]) for x in v.get("verified_languages") or [] if x.get("language")
            ]
            if language and langs and _iso_639_1(language) not in {_iso_639_1(x) for x in langs}:
                continue
            voices.append(
                Voice(
                    id=v["voice_id"],
                    name=v.get("name", v["voice_id"]),
                    languages=langs,
                    gender=(v.get("labels") or {}).get("gender"),
                )
            )
        return voices
