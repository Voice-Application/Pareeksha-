"""Azure AI Speech adapter: fast transcription (REST) and neural TTS (REST, SSML).

Docs (checked 2026-10-24): fast transcription
https://learn.microsoft.com/azure/ai-services/speech-service/fast-transcription-create
(``POST /speechtotext/transcriptions:transcribe?api-version=2025-10-15``, multipart ``audio`` +
``definition`` with ``locales``, ``diarization``, ``phraseList``); TTS REST
https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech
(SSML body, ``X-Microsoft-OutputFormat: riff-<rate>khz-16bit-mono-pcm``). Auth header
``Ocp-Apim-Subscription-Key``. Live streaming STT needs the Speech SDK's native session and is
not wired: ``streaming=False``.
"""

from __future__ import annotations

import json
import time
from typing import Any
from xml.sax.saxutils import escape, quoteattr

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
    Voice,
    WordTiming,
)
from pareeksha.speech.config import SpeechSettings
from pareeksha.speech.providers._common import HTTPAdapter, clamp01, elapsed_ms
from pareeksha.speech.wav import wav_info

API_VERSION = "2025-10-15"
OUTPUT_FORMATS = {
    8000: "riff-8khz-16bit-mono-pcm",
    16000: "riff-16khz-16bit-mono-pcm",
    22050: "riff-22050hz-16bit-mono-pcm",
    24000: "riff-24khz-16bit-mono-pcm",
    44100: "riff-44100hz-16bit-mono-pcm",
    48000: "riff-48khz-16bit-mono-pcm",
}


class AzureSTT(HTTPAdapter, STTProvider):
    provider = name = SpeechProviderName.AZURE
    capabilities = STTCapabilities(
        streaming=False,
        word_timings=True,
        word_confidence=False,  # confidence is reported per phrase, not per word
        diarization=True,
        max_batch_seconds=7200.0,  # fast transcription limit (<2 h, <300 MB) per Azure docs
        languages_note="hi-IN, ta-IN, te-IN, kn-IN, ml-IN, mr-IN, gu-IN, bn-IN, pa-IN, en-IN "
        "are listed Azure locales; accuracy pending real-key acceptance",
    )

    def __init__(
        self,
        settings: SpeechSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        retry_delay: float = 1.0,
        base_url: str | None = None,
    ) -> None:
        super().__init__(settings, client=client, retry_delay=retry_delay)
        self._base_url = (
            base_url or f"https://{self.settings.azure_speech_region}.api.cognitive.microsoft.com"
        )

    async def transcribe(
        self,
        wav: bytes,
        language: str,
        *,
        diarize: bool = False,
        num_speakers: int | None = None,
        bias_words: list[str] | None = None,
    ) -> Transcript:
        definition: dict[str, Any] = {"locales": [language]}
        if diarize:
            definition["diarization"] = {"enabled": True, "maxSpeakers": num_speakers or 2}
        if bias_words:
            definition["phraseList"] = {"phrases": bias_words}
        t0 = time.monotonic()
        response = await self._send(
            "POST",
            f"{self._base_url}/speechtotext/transcriptions:transcribe",
            params={"api-version": API_VERSION},
            headers={"Ocp-Apim-Subscription-Key": str(self.settings.azure_speech_key)},
            data={"definition": json.dumps(definition)},
            files={"audio": ("audio.wav", wav, "audio/wav")},
        )
        body: dict[str, Any] = response.json()
        if "phrases" not in body and "combinedPhrases" not in body:
            raise SpeechPermanentError("unexpected Azure STT response: no phrases")
        segments: list[TranscriptSegment] = []
        words: list[WordTiming] = []
        for p in body.get("phrases", []):
            start = p["offsetMilliseconds"] / 1000
            speaker = str(p["speaker"]) if "speaker" in p else None
            conf = clamp01(float(p["confidence"])) if "confidence" in p else None
            segments.append(
                TranscriptSegment(
                    text=p["text"],
                    start_s=start,
                    end_s=start + p["durationMilliseconds"] / 1000,
                    speaker=speaker,
                    confidence=conf,
                )
            )
            words += [
                WordTiming(
                    text=w["text"],
                    start_s=w["offsetMilliseconds"] / 1000,
                    end_s=(w["offsetMilliseconds"] + w["durationMilliseconds"]) / 1000,
                    speaker=speaker,
                )
                for w in p.get("words", [])
            ]
        text = " ".join(c["text"] for c in body.get("combinedPhrases", [])) or " ".join(
            s.text for s in segments
        )
        duration = float(body.get("durationMilliseconds", 0)) / 1000 or wav_info(wav)[1]
        confs = [s.confidence for s in segments if s.confidence is not None]
        return Transcript(
            provider=self.name,
            model=None,
            text=text,
            language=str((body.get("phrases") or [{}])[0].get("locale") or language),
            duration_s=duration,
            confidence=sum(confs) / len(confs) if confs else None,
            segments=segments,
            words=words,
            usage=SpeechUsage(
                provider=self.name,
                operation="stt_batch",
                audio_seconds=duration,
                latency_ms=elapsed_ms(t0),
                est_cost=self.settings.stt_cost(self.name, duration),
            ),
        )


class AzureTTS(HTTPAdapter, TTSProvider):
    provider = name = SpeechProviderName.AZURE
    capabilities = TTSCapabilities(
        sample_rates=tuple(OUTPUT_FORMATS),
        voice_listing=True,
        speed_control=True,
        voices_per_language=True,
        languages_note="Neural voices per locale (e.g. hi-IN-SwaraNeural, kn-IN-SapnaNeural); "
        "list with list_voices()",
    )

    def __init__(
        self,
        settings: SpeechSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        retry_delay: float = 1.0,
        base_url: str | None = None,
    ) -> None:
        super().__init__(settings, client=client, retry_delay=retry_delay)
        self._base_url = (
            base_url or f"https://{self.settings.azure_speech_region}.tts.speech.microsoft.com"
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
        voice_name = voice or self.settings.azure_tts_voice
        if not voice_name:
            raise SpeechPermanentError("azure TTS needs a voice name (arg or AZURE_TTS_VOICE)")
        fmt = OUTPUT_FORMATS.get(sample_rate)
        if fmt is None:
            raise SpeechPermanentError(f"azure supports {tuple(OUTPUT_FORMATS)}, not {sample_rate}")
        ssml = (
            f"<speak version='1.0' xml:lang={quoteattr(language)} "
            "xmlns='http://www.w3.org/2001/10/synthesis'>"
            f"<voice name={quoteattr(voice_name)}><prosody rate={quoteattr(f'{speed:g}')}>"
            f"{escape(text)}</prosody></voice></speak>"
        )
        t0 = time.monotonic()
        response = await self._send(
            "POST",
            f"{self._base_url}/cognitiveservices/v1",
            headers={
                "Ocp-Apim-Subscription-Key": str(self.settings.azure_speech_key),
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": fmt,
                "User-Agent": "pareeksha",
            },
            content=ssml.encode(),
        )
        audio = response.content
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
            f"{self._base_url}/cognitiveservices/voices/list",
            headers={"Ocp-Apim-Subscription-Key": str(self.settings.azure_speech_key)},
        )
        voices = [
            Voice(
                id=v["ShortName"],
                name=v.get("LocalName") or v["ShortName"],
                languages=[v["Locale"]],
                gender=v.get("Gender"),
            )
            for v in response.json()
        ]
        if language is None:
            return voices
        return [v for v in voices if v.languages[0].lower() == language.lower()]
