"""Deepgram adapter: Nova STT (prerecorded REST + live WebSocket) and Aura TTS (REST).

Docs (checked 2026-10-24): https://developers.deepgram.com/docs/pre-recorded-audio,
https://developers.deepgram.com/reference/manage/models/list. Auth header ``Authorization: Token``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlencode

import httpx
import websockets

from pareeksha.speech.base import (
    SpeechPermanentError,
    SpeechProviderName,
    SpeechRetryableError,
    SpeechUsage,
    StreamingTranscript,
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

BASE_URL = "https://api.deepgram.com"
WS_URL = "wss://api.deepgram.com"


def deepgram_language(language: str) -> str:
    """``hi-IN`` -> ``hi``; English keeps its region (``en-IN``), which Deepgram lists."""
    if language.lower().startswith("en-") or "-" not in language:
        return language
    return language.split("-", 1)[0]


class DeepgramSTT(HTTPAdapter, STTProvider):
    provider = name = SpeechProviderName.DEEPGRAM
    capabilities = STTCapabilities(
        streaming=True,
        word_timings=True,
        word_confidence=True,
        diarization=True,
        languages_note="Nova-3 language list per Deepgram docs; Indian-language coverage "
        "(hi, en-IN, ta, te...) is to be confirmed with the owner's key",
    )

    def __init__(
        self,
        settings: SpeechSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        retry_delay: float = 1.0,
        base_url: str = BASE_URL,
        ws_url: str = WS_URL,
    ) -> None:
        super().__init__(settings, client=client, retry_delay=retry_delay)
        self._base_url = base_url
        self._ws_url = ws_url

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self.settings.deepgram_api_key}"}

    async def transcribe(
        self,
        wav: bytes,
        language: str,
        *,
        diarize: bool = False,
        num_speakers: int | None = None,
        bias_words: list[str] | None = None,
    ) -> Transcript:
        model = self.settings.deepgram_stt_model
        params: list[tuple[str, str]] = [
            ("model", model),
            ("language", deepgram_language(language)),
            ("punctuate", "true"),
            ("smart_format", "true"),
        ]
        if diarize:
            params.append(("diarize", "true"))
        params += [("keyterm", w) for w in bias_words or []]
        t0 = time.monotonic()
        response = await self._send(
            "POST",
            f"{self._base_url}/v1/listen",
            params=params,
            headers={**self._headers, "Content-Type": "audio/wav"},
            content=wav,
        )
        body = response.json()
        try:
            alt = body["results"]["channels"][0]["alternatives"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise SpeechPermanentError(f"unexpected Deepgram response shape: {exc!r}") from exc
        duration = float(body.get("metadata", {}).get("duration") or wav_info(wav)[1])
        words = [
            WordTiming(
                text=w.get("punctuated_word") or w["word"],
                start_s=float(w["start"]),
                end_s=float(w["end"]),
                confidence=clamp01(float(w["confidence"])) if "confidence" in w else None,
                speaker=str(w["speaker"]) if "speaker" in w else None,
            )
            for w in alt.get("words", [])
        ]
        text = alt.get("transcript", "")
        segments = _speaker_segments(words) if diarize and words else []
        if not segments and text:
            end = words[-1].end_s if words else duration
            segments = [
                TranscriptSegment(text=text, start_s=words[0].start_s if words else 0, end_s=end)
            ]
        return Transcript(
            provider=self.name,
            model=model,
            text=text,
            language=language,
            duration_s=duration,
            confidence=clamp01(float(alt["confidence"])) if "confidence" in alt else None,
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

    async def transcribe_stream(
        self, pcm_chunks: AsyncIterator[bytes], language: str, *, sample_rate: int = 16000
    ) -> AsyncIterator[StreamingTranscript]:
        query = urlencode(
            {
                "model": self.settings.deepgram_stt_model,
                "language": deepgram_language(language),
                "encoding": "linear16",
                "sample_rate": sample_rate,
                "channels": 1,
                "interim_results": "true",
                "smart_format": "true",
            }
        )
        try:
            async with websockets.connect(
                f"{self._ws_url}/v1/listen?{query}", additional_headers=self._headers
            ) as ws:

                async def pump() -> None:
                    async for chunk in pcm_chunks:
                        await ws.send(chunk)
                    await ws.send(json.dumps({"type": "CloseStream"}))

                sender = asyncio.create_task(pump())
                try:
                    async for raw in ws:
                        if isinstance(raw, bytes):
                            continue
                        msg: dict[str, Any] = json.loads(raw)
                        if msg.get("type") != "Results":
                            continue
                        alt = msg["channel"]["alternatives"][0]
                        if not alt.get("transcript"):
                            continue
                        start = float(msg.get("start", 0.0))
                        yield StreamingTranscript(
                            text=alt["transcript"],
                            is_final=bool(msg.get("is_final")),
                            confidence=clamp01(float(alt["confidence"]))
                            if "confidence" in alt
                            else None,
                            start_s=start,
                            end_s=start + float(msg.get("duration", 0.0)),
                        )
                finally:
                    sender.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sender
        except websockets.InvalidStatus as exc:
            code = exc.response.status_code
            if code >= 500 or code == 429:
                raise SpeechRetryableError(f"Deepgram stream HTTP {code}") from exc
            raise SpeechPermanentError(f"Deepgram stream HTTP {code}") from exc
        except (OSError, websockets.ConnectionClosedError) as exc:
            raise SpeechRetryableError(f"Deepgram stream: {type(exc).__name__}: {exc}") from exc


def _speaker_segments(words: list[WordTiming]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    group: list[WordTiming] = []
    for w in words:
        if group and w.speaker != group[-1].speaker:
            segments.append(_segment(group))
            group = []
        group.append(w)
    if group:
        segments.append(_segment(group))
    return segments


def _segment(group: list[WordTiming]) -> TranscriptSegment:
    confs = [w.confidence for w in group if w.confidence is not None]
    return TranscriptSegment(
        text=" ".join(w.text for w in group),
        start_s=group[0].start_s,
        end_s=group[-1].end_s,
        speaker=group[0].speaker,
        confidence=sum(confs) / len(confs) if confs else None,
    )


class DeepgramTTS(HTTPAdapter, TTSProvider):
    provider = name = SpeechProviderName.DEEPGRAM
    capabilities = TTSCapabilities(
        sample_rates=(8000, 16000, 24000, 32000, 48000),
        voice_listing=True,
        speed_control=False,
        voices_per_language=True,
        languages_note="Aura voices are per language; Indian languages are not offered "
        "(English voices only at the time of writing)",
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

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Token {self.settings.deepgram_api_key}"}

    async def synthesize(
        self,
        text: str,
        voice: str | None,
        language: str,
        *,
        sample_rate: int = 16000,
        speed: float = 1.0,
    ) -> SynthesisResult:
        if speed != 1.0:
            raise UnsupportedCapabilityError("deepgram TTS has no speed control")
        model = voice or self.settings.deepgram_tts_model
        t0 = time.monotonic()
        response = await self._send(
            "POST",
            f"{self._base_url}/v1/speak",
            params={
                "model": model,
                "encoding": "linear16",
                "container": "wav",
                "sample_rate": str(sample_rate),
            },
            headers=self._headers,
            json={"text": text},
        )
        audio = response.content
        rate, secs = wav_info(audio)
        return SynthesisResult(
            provider=self.name,
            voice=model,
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
        response = await self._send("GET", f"{self._base_url}/v1/models", headers=self._headers)
        voices = [
            Voice(
                id=m["canonical_name"],
                name=m.get("name", m["canonical_name"]),
                languages=list(m.get("languages", [])),
                gender=None,
            )
            for m in response.json().get("tts", [])
        ]
        if language is None:
            return voices
        base = language.split("-", 1)[0].lower()
        return [v for v in voices if any(x.lower().split("-", 1)[0] == base for x in v.languages)]
