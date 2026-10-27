"""Fakes for caller-pipeline tests: scripted STT, TTS and brain, plus an energy VAD."""

from __future__ import annotations

import array
import asyncio
import contextlib
import io
import json
import uuid
import wave
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any, ClassVar

from pipecat.audio.vad.vad_analyzer import VADAnalyzer, VADParams
from websockets.asyncio.server import ServerConnection, serve

from pareeksha.adapters.base import AgentTarget
from pareeksha.audio.profiles import get_profile
from pareeksha.llm.caller import HistoryLine
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate
from pareeksha.simulation.models import CallSpec, SimulationSettings
from pareeksha.simulation.runtime import CallerLine
from pareeksha.simulation.vad import EnergyVADAnalyzer, frame_rms
from pareeksha.speech.base import (
    SpeechProviderName,
    SpeechUsage,
    STTCapabilities,
    STTProvider,
    SynthesisResult,
    Transcript,
    TTSCapabilities,
    TTSProvider,
    Voice,
)

#: 20 ms of square wave at ~4000 amplitude: loud enough for the energy VAD.
LOUD_FRAME = array.array("h", [4000, -4000] * 160).tobytes()


def tone_wav(seconds: float, sample_rate: int = 16000) -> bytes:
    n = int(seconds * sample_rate)
    samples = array.array("h", ([4000, -4000] * (n // 2 + 1))[:n])
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())
    return out.getvalue()


class FakeSTT(STTProvider):
    name: ClassVar[SpeechProviderName] = SpeechProviderName.GNANI
    capabilities: ClassVar[STTCapabilities] = STTCapabilities(
        streaming=False, word_timings=False, word_confidence=False, diarization=False
    )

    def __init__(self, texts: Sequence[str] = (), *, fail: bool = False) -> None:
        self.texts = list(texts)
        self.fail = fail
        self.calls = 0
        self.seconds: list[float] = []

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
        from pareeksha.speech.base import SpeechRetryableError
        from pareeksha.speech.wav import wav_info

        self.calls += 1
        if self.fail:
            raise SpeechRetryableError("fake stt outage")
        _, duration = wav_info(wav)
        self.seconds.append(duration)
        text = self.texts.pop(0) if self.texts else "okay"
        return Transcript(
            provider=self.name,
            text=text,
            language=language,
            duration_s=duration,
            confidence=0.9,
            usage=SpeechUsage(provider=self.name, operation="stt_rest", audio_seconds=duration),
        )

    async def aclose(self) -> None:
        return None


class FakeTTS(TTSProvider):
    name: ClassVar[SpeechProviderName] = SpeechProviderName.GNANI
    capabilities: ClassVar[TTSCapabilities] = TTSCapabilities(
        sample_rates=(16000,), voice_listing=False, speed_control=True
    )

    def __init__(
        self,
        seconds_per_char: float = 0.02,
        minimum_s: float = 0.4,
        delays: dict[str, float] | None = None,
    ) -> None:
        #: text fragment -> seconds the synthesis takes (to make one part of a line late)
        self.delays = delays or {}
        self.said: list[str] = []
        self.voices: list[str | None] = []
        self.speeds: list[float] = []
        self._per_char = seconds_per_char
        self._min = minimum_s
        self.fail = False

    async def synthesize(
        self,
        text: str,
        voice: str | None,
        language: str,
        *,
        sample_rate: int = 16000,
        speed: float = 1.0,
    ) -> SynthesisResult:
        from pareeksha.speech.base import SpeechPermanentError

        if self.fail:
            raise SpeechPermanentError("fake tts outage")
        for fragment, delay in self.delays.items():
            if fragment in text:
                await asyncio.sleep(delay)
        self.said.append(text)
        self.voices.append(voice)
        self.speeds.append(speed)
        seconds = max(self._min, len(text) * self._per_char)
        return SynthesisResult(
            provider=self.name,
            voice=voice or "fake",
            audio=tone_wav(seconds, sample_rate),
            sample_rate=sample_rate,
            duration_s=seconds,
            usage=SpeechUsage(provider=self.name, operation="tts", characters=len(text)),
        )

    async def list_voices(self, language: str | None = None) -> list[Voice]:
        return []

    async def aclose(self) -> None:
        return None


class ScriptedCaller:
    """``CallerSource`` returning the given lines in order (then a closing line)."""

    def __init__(self, lines: Sequence[str | CallerLine], *, fail_after: int | None = None) -> None:
        self.lines = [CallerLine(x) if isinstance(x, str) else x for x in lines]
        self.fail_after = fail_after
        self.histories: list[list[HistoryLine]] = []
        self.turn_numbers: list[int] = []

    async def next_line(
        self,
        persona: PersonaCreate,
        scenario: ScenarioCreate,
        history: Sequence[HistoryLine],
        turn_number: int,
    ) -> CallerLine:
        self.histories.append(list(history))
        self.turn_numbers.append(turn_number)
        if self.fail_after is not None and len(self.histories) > self.fail_after:
            raise RuntimeError("fake llm outage")
        if self.lines:
            return self.lines.pop(0)
        return CallerLine("okay thank you", end_call=True)


def energy_vad(settings: SimulationSettings) -> VADAnalyzer:
    return EnergyVADAnalyzer(
        params=VADParams(
            confidence=0.5,
            start_secs=settings.vad_start_s,
            stop_secs=settings.end_of_turn_s,
            min_volume=0.0,
        )
    )


FAST = SimulationSettings(
    end_of_turn_s=0.3,
    vad_start_s=0.06,
    preroll_ms=100,
    min_utterance_ms=100,
    first_silence_s=0.8,
    mid_silence_s=0.8,
    goodbye_tail_s=0.2,
    long_pause_s=(0.2, 0.3),
    goes_silent_s=0.5,
)


def persona(**over: Any) -> PersonaCreate:
    base: dict[str, Any] = {"name": "Test caller", "language": "en-IN", "voice_id": "Vasudha"}
    return PersonaCreate(**{**base, **over})


def scenario(**over: Any) -> ScenarioCreate:
    base: dict[str, Any] = {
        "title": "t",
        "caller_goal": "promise to pay on Friday",
        "success_criteria": "promise recorded",
        "max_turns": 6,
    }
    return ScenarioCreate(**{**base, **over})


def make_spec(
    endpoint: str,
    *,
    persona_over: dict[str, Any] | None = None,
    scenario_over: dict[str, Any] | None = None,
    profile: str = "clean_16k",
    seed: int = 1,
    max_call_seconds: int = 60,
    metadata: dict[str, Any] | None = None,
) -> CallSpec:
    return CallSpec(
        call_id=uuid.uuid4(),
        agent=AgentTarget(
            agent_id=uuid.uuid4(), adapter="audio_v1", endpoint_url=endpoint, glass_box=True
        ),
        persona=persona(**(persona_over or {})),
        scenario=scenario(**(scenario_over or {})),
        profile=get_profile(profile),
        seed=seed,
        max_call_seconds=max_call_seconds,
        metadata=metadata or {},
    )


async def aiter_list(items: Sequence[Any]) -> AsyncIterator[Any]:
    for item in items:
        yield item


# --------------------------------------------------------------------------- tiny test agents

Handler = Callable[[ServerConnection], Awaitable[None]]


@contextlib.asynccontextmanager
async def agent_server(handler: Handler) -> AsyncIterator[str]:
    """A WebSocket agent running ``handler`` per connection; yields its ``ws://`` URL."""
    async with serve(handler, "127.0.0.1", 0) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"ws://127.0.0.1:{port}/call"


async def read_start(ws: ServerConnection) -> dict[str, Any]:
    start = json.loads(await ws.recv())
    assert start["type"] == "start"
    return dict(start)


async def send_tone(ws: ServerConnection, seconds: float) -> None:
    """Agent speech: loud 20 ms frames at real-time pace."""
    for _ in range(int(seconds * 50)):
        await ws.send(LOUD_FRAME)
        await asyncio.sleep(0.02)


class ReactiveAgent:
    """A scripted agent: speaks ``turns`` (seconds each), the next one after the caller has spoken.

    ``honour`` = stops talking when the caller talks over it. ``hangup`` = sends ``call_end`` after
    the last turn. ``speak_first`` = the first turn starts without waiting for the caller.
    ``quiet_frames`` = 20 ms frames of caller silence before the agent takes its turn.
    """

    def __init__(
        self,
        turns: Sequence[float],
        *,
        honour: bool = True,
        hangup: bool = False,
        speak_first: bool = True,
        glass_box: bool = True,
        quiet_frames: int = 15,
    ) -> None:
        self.quiet_frames = quiet_frames
        self.turns = list(turns)
        self.honour = honour
        self.hangup = hangup
        self.speak_first = speak_first
        self.glass_box = glass_box
        self.started: list[dict[str, Any]] = []
        self.stopped_early = 0
        self.caller_frames = 0
        self._played = 0
        self._speech: asyncio.Task[None] | None = None

    async def __call__(self, ws: ServerConnection) -> None:
        self.started.append(await read_start(ws))
        if self.speak_first:
            self._next_turn(ws)
        loud_run = quiet_run = 0
        heard = False
        try:
            async for message in ws:
                if not isinstance(message, bytes):
                    continue
                self.caller_frames += 1
                if frame_rms(message) >= 500:
                    loud_run, quiet_run, heard = loud_run + 1, 0, True
                    if self.honour and self._speaking() and loud_run >= 5:
                        assert self._speech is not None
                        self._speech.cancel()
                        self.stopped_early += 1
                else:
                    loud_run, quiet_run = 0, quiet_run + 1
                    if heard and quiet_run >= self.quiet_frames:
                        heard = False
                        if not self._speaking():  # talked over and ignored: nothing to answer
                            self._next_turn(ws)
        finally:
            if self._speech is not None:
                self._speech.cancel()

    def _speaking(self) -> bool:
        return self._speech is not None and not self._speech.done()

    def _next_turn(self, ws: ServerConnection) -> None:
        if self._played >= len(self.turns):
            return
        seconds = self.turns[self._played]
        self._played += 1
        last = self._played == len(self.turns)
        self._speech = asyncio.create_task(self._speak(ws, seconds, last))

    async def _speak(self, ws: ServerConnection, seconds: float, last: bool) -> None:
        if self.glass_box:
            text = json.dumps(
                {"type": "transcript", "role": "agent", "text": f"turn {self._played}"}
            )
            await ws.send(text)
        await send_tone(ws, seconds)
        if last and self.hangup:
            await ws.send(json.dumps({"type": "call_end", "reason": "completed"}))
            await ws.close()


async def echo_agent(ws: ServerConnection) -> None:
    """Sends every caller frame straight back (the NFR-2 loopback agent)."""
    await read_start(ws)
    async for message in ws:
        if isinstance(message, bytes):
            await ws.send(message)
