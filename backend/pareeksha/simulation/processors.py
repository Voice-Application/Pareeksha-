"""Pipecat processors of the caller pipeline (docs/03-TRD.md section 5).

::

    AgentSource > CallTap > AgentTurnDetector > AgentSTT > CallerDirector > CallerTTS > CallerMic
                                                                ^                           |
                                                                +-- speech started/ended ---+

- ``AgentSource`` is the input transport: it turns ``AudioSession`` events into frames.
- ``CallTap`` stamps the agent side onto the recorder, the turn tracker and the event log.
- ``AgentTurnDetector`` runs Pipecat's VAD analyzer (Silero) and cuts the agent's audio into turns.
- ``AgentSTT`` is the caller-side speech recognition (any ``STTProvider``).
- ``CallerDirector`` (``director.py``) is the caller: when to answer, interrupt, nudge or hang up.
- ``CallerTTS`` voices the line with the persona's voice (any ``TTSProvider``).
- ``CallerMic`` is the output transport and the line: a drift-free 20 ms clock that sends the
  speech, or silence, through the ``LineSimulator`` to the agent and records what it sent.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any

from pipecat.audio.vad.vad_analyzer import VADAnalyzer
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    StartFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pareeksha.adapters.base import (
    AUDIO_FRAME_BYTES,
    AUDIO_FRAME_MS,
    AUDIO_SAMPLE_RATE,
    AdapterError,
    AgentAudio,
    AgentCallEnd,
    AgentToolCall,
    AgentTranscript,
    AudioSession,
    SessionClosedError,
)
from pareeksha.audio.line_simulator import LineSimulator
from pareeksha.simulation.audio_util import wav_to_pcm16
from pareeksha.simulation.frames import (
    AgentHangupFrame,
    AgentHeardFrame,
    AgentSpeechEndedFrame,
    AgentSpeechStartedFrame,
    AgentStreamEndedFrame,
    AgentToolCallFrame,
    AgentTranscriptFrame,
    AgentUtteranceFrame,
    CallerSpeechEndedFrame,
    CallerSpeechFrame,
    CallerSpeechStartedFrame,
    CancelSpeakFrame,
    SpeakRequestFrame,
)
from pareeksha.simulation.models import UsageItem
from pareeksha.simulation.recorder import SAMPLE_RATE
from pareeksha.simulation.runtime import CallRuntime
from pareeksha.simulation.vad import SpeechGate
from pareeksha.speech.base import STTProvider, TTSProvider
from pareeksha.speech.wav import pcm_to_wav

log = logging.getLogger(__name__)

STT_TIMEOUT_S = 25.0
TTS_TIMEOUT_S = 25.0
_SILENCE = bytes(AUDIO_FRAME_BYTES)


class CallProcessor(FrameProcessor):
    """Base class: owns background tasks and cancels them on cleanup."""

    def __init__(self, rt: CallRuntime, name: str) -> None:
        super().__init__(name=name)
        self.rt = rt
        self._bg: list[asyncio.Task[Any]] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        try:
            await self.handle(frame, direction)
        except Exception as exc:  # a bug or provider fault must end the call, not hang it
            self.fail(self.name, exc)

    async def handle(self, frame: Frame, direction: FrameDirection) -> None:
        """Subclass hook: react to ``frame`` and forward it (every frame must be forwarded)."""
        await self.push_frame(frame, direction)

    def spawn(self, coro: Coroutine[Any, Any, None], name: str) -> asyncio.Task[Any]:
        task = self.create_task(coro, name)
        self._bg.append(task)
        return task

    async def stop_background(self) -> None:
        tasks, self._bg = self._bg, []
        for task in tasks:
            if not task.done():
                await self.cancel_task(task)

    async def cleanup(self) -> None:
        await self.stop_background()
        await super().cleanup()  # type: ignore[no-untyped-call]

    def fail(self, where: str, exc: BaseException) -> None:
        log.error("%s failed: %s: %s", where, type(exc).__name__, exc)
        self.rt.finish("infra_error", f"{where}: {type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- input side


class AgentSource(CallProcessor):
    """Input transport: ``AudioSession.receive()`` -> frames, stamped on the call clock."""

    def __init__(self, rt: CallRuntime, session: AudioSession) -> None:
        super().__init__(rt, "AgentSource")
        self._session = session

    async def handle(self, frame: Frame, direction: FrameDirection) -> None:
        await self.push_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self.spawn(self._pump(), "pump")

    async def _pump(self) -> None:
        clock = self.rt.clock
        try:
            async for event in self._session.receive():
                t = clock.now_ms()
                if isinstance(event, AgentAudio):
                    audio = InputAudioRawFrame(
                        audio=event.pcm16, sample_rate=AUDIO_SAMPLE_RATE, num_channels=1
                    )
                    audio.metadata["t_ms"] = t
                    audio.metadata["t_mono"] = time.monotonic()
                    await self.push_frame(audio)
                elif isinstance(event, AgentTranscript):
                    await self.push_frame(
                        AgentTranscriptFrame(
                            role=event.role, text=event.text, is_final=event.is_final, t_ms=t
                        )
                    )
                elif isinstance(event, AgentToolCall):
                    await self.push_frame(
                        AgentToolCallFrame(
                            tool_name=event.name,
                            arguments=event.arguments,
                            result=event.result,
                            t_ms=t,
                        )
                    )
                elif isinstance(event, AgentCallEnd):
                    await self.push_frame(AgentHangupFrame(reason=event.reason, t_ms=t))
                    return
        except AdapterError as exc:
            self.fail("agent transport", exc)


class CallTap(CallProcessor):
    """Stamps the agent's audio and glass-box messages onto the recorder, tracker and event log."""

    def __init__(self, rt: CallRuntime) -> None:
        super().__init__(rt, "CallTap")
        self._first_audio = True

    async def handle(self, frame: Frame, direction: FrameDirection) -> None:
        rt = self.rt
        if isinstance(frame, InputAudioRawFrame):
            t = int(frame.metadata["t_ms"])
            rt.hop_ms.append((time.monotonic() - frame.metadata["t_mono"]) * 1000)
            rt.recorder.add_agent(frame.audio, t)
            if self._first_audio:
                self._first_audio = False
                rt.log("agent_audio_first", t_ms=t)
        elif isinstance(frame, AgentTranscriptFrame):
            rt.log("agent_transcript", t_ms=frame.t_ms, role=frame.role, text=frame.text)
            if frame.is_final and frame.text:
                if frame.role == "user":
                    rt.tracker.add_agent_heard(frame.t_ms, frame.text)
                else:
                    rt.tracker.add_agent_said(frame.t_ms, frame.text)
        elif isinstance(frame, AgentToolCallFrame):
            rt.log("agent_tool_call", t_ms=frame.t_ms, name=frame.tool_name)
            rt.tracker.add_tool_call(frame.t_ms, frame.tool_name, frame.arguments, frame.result)
        elif isinstance(frame, AgentHangupFrame):
            rt.log("agent_hangup", t_ms=frame.t_ms, reason=frame.reason)
        await self.push_frame(frame, direction)


class AgentTurnDetector(CallProcessor):
    """Cuts the agent's audio into turns with a Pipecat VAD analyzer.

    Agents may leave silence out, so a 20 ms ticker feeds the analyzer silence whenever no audio
    arrives; otherwise the end of a turn could never be detected. Consumes the audio frames
    (nothing downstream needs them) and emits speech start/end system frames plus one
    ``AgentUtteranceFrame`` per turn.
    """

    def __init__(self, rt: CallRuntime, analyzer: VADAnalyzer) -> None:
        super().__init__(rt, "AgentTurnDetector")
        self._gate = SpeechGate(analyzer)
        s = rt.settings
        self._keep_ms = s.preroll_ms + int(s.vad_start_s * 1000) + 120
        self._frames: deque[tuple[int, bytes]] = deque()
        self._lock = asyncio.Lock()
        self._virtual_ms = 0
        self._speech_start_ms: int | None = None
        self._closed = False

    async def handle(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            self._virtual_ms = self.rt.clock.now_ms()
            self.spawn(self._ticker(), "ticker")
            return
        if isinstance(frame, InputAudioRawFrame):
            async with self._lock:
                arrived = int(frame.metadata["t_ms"])
                await self._fill_until(arrived - AUDIO_FRAME_MS)
                self._virtual_ms = max(arrived, self._virtual_ms + AUDIO_FRAME_MS)
                await self._feed(frame.audio, self._virtual_ms)
            return
        elif isinstance(frame, AgentHangupFrame):
            async with self._lock:
                await self._flush(frame.t_ms)
            await self.push_frame(frame, direction)
            await self.push_frame(AgentStreamEndedFrame(reason=frame.reason, t_ms=frame.t_ms))
            return
        await self.push_frame(frame, direction)

    async def _ticker(self) -> None:
        period = AUDIO_FRAME_MS / 1000
        next_at = time.monotonic() + period
        while not self._closed:
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))
            next_at += period
            async with self._lock:
                await self._fill_until(self.rt.clock.now_ms() - AUDIO_FRAME_MS)

    async def _fill_until(self, target_ms: int) -> None:
        while target_ms - self._virtual_ms >= AUDIO_FRAME_MS:
            self._virtual_ms += AUDIO_FRAME_MS
            await self._feed(_SILENCE, self._virtual_ms)

    async def _feed(self, pcm: bytes, t_ms: int) -> None:
        self._frames.append((t_ms, pcm))
        edges = await self._gate.feed(pcm, t_ms)
        if not self._gate.speaking and self._speech_start_ms is None:
            while self._frames and self._frames[0][0] < t_ms - self._keep_ms:
                self._frames.popleft()
        for edge in edges:
            if edge.kind == "start":
                self._speech_start_ms = edge.t_ms
                self.rt.log("agent_speech_start", t_ms=edge.t_ms, detected_ms=edge.detected_ms)
                await self.push_frame(AgentSpeechStartedFrame(t_ms=edge.t_ms))
            else:
                await self._emit_turn(edge.t_ms)

    async def _flush(self, now_ms: int) -> None:
        edge = self._gate.flush(now_ms)
        if edge is not None:
            await self._emit_turn(edge.t_ms)

    async def _emit_turn(self, end_ms: int) -> None:
        start_ms = self._speech_start_ms if self._speech_start_ms is not None else end_ms
        self._speech_start_ms = None
        s = self.rt.settings
        self.rt.log("agent_speech_end", t_ms=end_ms, start_ms=start_ms)
        await self.push_frame(AgentSpeechEndedFrame(start_ms=start_ms, t_ms=end_ms))
        lo, hi = start_ms - s.preroll_ms, end_ms + 300
        pcm = b"".join(p for t, p in self._frames if lo <= t <= hi)
        self._frames.clear()
        if end_ms - start_ms < s.min_utterance_ms or not pcm:
            self.rt.log("agent_noise_burst", t_ms=end_ms, duration_ms=end_ms - start_ms)
            return
        await self.push_frame(AgentUtteranceFrame(pcm=pcm, start_ms=start_ms, end_ms=end_ms))

    async def cleanup(self) -> None:
        self._closed = True
        await super().cleanup()
        await self._gate.cleanup()


class AgentSTT(CallProcessor):
    """Caller-side speech recognition of each agent turn (FR-RN-8 ``text``)."""

    def __init__(self, rt: CallRuntime, stt: STTProvider) -> None:
        super().__init__(rt, "AgentSTT")
        self._stt = stt

    async def handle(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, AgentUtteranceFrame):
            await self.push_frame(await self._hear(frame))
            return
        await self.push_frame(frame, direction)

    async def _hear(self, utt: AgentUtteranceFrame) -> AgentHeardFrame:
        rt = self.rt
        language = rt.spec.language
        wav = pcm_to_wav(utt.pcm, AUDIO_SAMPLE_RATE)
        started = rt.clock.now_ms()
        try:
            result = await asyncio.wait_for(
                self._stt.transcribe(wav, language), timeout=STT_TIMEOUT_S
            )
        except Exception as exc:  # any provider fault is one unreadable turn, not a dead call
            rt.log("stt_error", error=f"{type(exc).__name__}: {exc}")
            return AgentHeardFrame(
                text="", start_ms=utt.start_ms, end_ms=utt.end_ms, stt_failed=True
            )
        u = result.usage
        rt.usage.append(
            UsageItem(
                kind="stt",
                provider=u.provider.value,
                operation=u.operation,
                audio_seconds=u.audio_seconds,
                est_cost=u.est_cost,
                latency_ms=u.latency_ms,
            )
        )
        text = result.text.strip()
        rt.log(
            "agent_heard",
            text=text,
            stt_ms=rt.clock.now_ms() - started,
            start_ms=utt.start_ms,
            end_ms=utt.end_ms,
        )
        return AgentHeardFrame(
            text=text,
            start_ms=utt.start_ms,
            end_ms=utt.end_ms,
            confidence=result.confidence,
            language=result.language,
        )


# --------------------------------------------------------------------------- output side


SENTENCE_END = re.compile(r"(?<=[.!?\u0964\u0965])\s+")
#: Texts shorter than this are synthesised in one request; longer ones are cut after the first
#: sentence so playback can start while the rest is still being synthesised.
CHUNK_MIN_CHARS = 60


def split_for_tts(text: str) -> list[str]:
    """``[first sentence, rest]`` for a long multi-sentence line, else ``[text]``."""
    if len(text) < CHUNK_MIN_CHARS:
        return [text]
    parts = SENTENCE_END.split(text.strip(), maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return [text]
    return [parts[0].strip(), parts[1].strip()]


class CallerTTS(CallProcessor):
    """Voices the caller's line with the persona's voice and speed (any ``TTSProvider``).

    A long line is synthesised as two requests, one after the other (first sentence, rest; Gnani
    allows one active request per key), and each part is forwarded as soon as it is ready, so the
    caller starts talking after the first sentence's synthesis time instead of the whole line's
    and the rest is synthesised while the first sentence plays.
    """

    def __init__(self, rt: CallRuntime, tts: TTSProvider) -> None:
        super().__init__(rt, "CallerTTS")
        self._tts = tts

    async def handle(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, SpeakRequestFrame):
            await self._speak(frame)
            return
        await self.push_frame(frame, direction)

    async def _speak(self, req: SpeakRequestFrame) -> None:
        texts = split_for_tts(req.text)
        for index, text in enumerate(texts):
            pcm = await self._synthesize(req, text)
            if pcm is None:
                return
            await self.push_frame(
                CallerSpeechFrame(
                    utt_id=req.utt_id,
                    text=req.text,
                    kind=req.kind,
                    pcm=pcm,
                    play_at_ms=req.play_at_ms,
                    final=req.final,
                    last_part=index == len(texts) - 1,
                )
            )

    async def _synthesize(self, req: SpeakRequestFrame, text: str) -> bytes | None:
        rt = self.rt
        persona = rt.spec.persona
        try:
            result = await asyncio.wait_for(
                self._tts.synthesize(
                    text,
                    persona.voice_id,
                    persona.language,
                    sample_rate=SAMPLE_RATE,
                    speed=persona.speed,
                ),
                timeout=TTS_TIMEOUT_S,
            )
            pcm = wav_to_pcm16(result.audio)
        except Exception as exc:
            self.fail("caller TTS", exc)
            return None
        u = result.usage
        rt.usage.append(
            UsageItem(
                kind="tts",
                provider=u.provider.value,
                operation=u.operation,
                audio_seconds=result.duration_s,
                characters=len(text),
                est_cost=u.est_cost,
                latency_ms=u.latency_ms,
                cached=u.characters == 0,
            )
        )
        rt.log(
            "caller_tts",
            utt_id=req.utt_id,
            tts_ms=u.latency_ms,
            seconds=result.duration_s,
            characters=len(text),
        )
        return pcm


@dataclass
class _Playing:
    utt_id: int
    pcm: bytearray
    more: bool
    offset: int = 0
    started: bool = False
    start_ms: int = 0


class CallerMic(CallProcessor):
    """Output transport: the caller's microphone and the phone line.

    Every 20 ms it takes the next 20 ms of caller speech (or silence), passes it through the
    ``LineSimulator`` so line noise is present even while the caller is quiet, sends it to the agent
    and records it. Speech start/end are reported upstream the moment the first/last speech frame is
    sent, which is the "caller last frame sent" time that latency is measured from. An utterance
    arriving in parts keeps playing as the parts arrive (silence if the next part is late).
    """

    def __init__(self, rt: CallRuntime, session: AudioSession, line: LineSimulator) -> None:
        super().__init__(rt, "CallerMic")
        self._session = session
        self._line = line
        self._pending: deque[CallerSpeechFrame] = deque()
        self._cancelled: set[int] = set()
        self._playing: _Playing | None = None

    async def handle(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            self.spawn(self._run(), "mic")
            return
        if isinstance(frame, CallerSpeechFrame):
            playing = self._playing
            if playing is not None and playing.utt_id == frame.utt_id:
                playing.pcm += frame.pcm
                playing.more = not frame.last_part
            else:
                self._pending.append(frame)
        elif isinstance(frame, CancelSpeakFrame):
            self._cancelled.add(frame.utt_id)
        elif isinstance(frame, EndFrame | CancelFrame):
            await self.stop_background()
        await self.push_frame(frame, direction)

    def _next_utterance(self, now_ms: int) -> _Playing | None:
        while self._pending and self._pending[0].utt_id in self._cancelled:
            dropped = self._pending.popleft()
            self.rt.log("caller_utterance_dropped", utt_id=dropped.utt_id)
        if not self._pending:
            return None
        head = self._pending[0]
        if head.play_at_ms is not None and now_ms < head.play_at_ms:
            return None
        playing = _Playing(head.utt_id, bytearray(), more=True)
        while self._pending and self._pending[0].utt_id == head.utt_id:
            part = self._pending.popleft()
            playing.pcm += part.pcm
            playing.more = not part.last_part
        return playing

    async def _run(self) -> None:
        rt = self.rt
        period = AUDIO_FRAME_MS / 1000
        origin_ms = rt.clock.now_ms()
        sent = 0
        out = bytearray()
        next_at = time.monotonic()
        try:
            while True:
                if self._playing is None:
                    self._playing = self._next_utterance(rt.clock.now_ms())
                playing = self._playing
                chunk = _SILENCE
                ended = False
                if playing is not None:
                    if playing.offset < len(playing.pcm) or not playing.more:
                        chunk = bytes(
                            playing.pcm[playing.offset : playing.offset + AUDIO_FRAME_BYTES]
                        ).ljust(AUDIO_FRAME_BYTES, b"\x00")
                        playing.offset += AUDIO_FRAME_BYTES
                        ended = playing.offset >= len(playing.pcm) and not playing.more
                    if not playing.started:
                        playing.started = True
                        playing.start_ms = rt.clock.now_ms()
                        await self.push_frame(
                            CallerSpeechStartedFrame(utt_id=playing.utt_id, t_ms=playing.start_ms),
                            FrameDirection.UPSTREAM,
                        )
                out += self._line.process_pcm16(chunk)
                if len(out) >= AUDIO_FRAME_BYTES:
                    frame = bytes(out[:AUDIO_FRAME_BYTES])
                    del out[:AUDIO_FRAME_BYTES]
                    await self._session.send_pcm16(frame)
                    rt.recorder.add_caller(frame, origin_ms + sent * AUDIO_FRAME_MS)
                    sent += 1
                if ended and playing is not None:
                    self._playing = None
                    await self.push_frame(
                        CallerSpeechEndedFrame(
                            utt_id=playing.utt_id,
                            t_ms=rt.clock.now_ms(),
                            start_ms=playing.start_ms,
                        ),
                        FrameDirection.UPSTREAM,
                    )
                next_at += period
                lag = next_at - time.monotonic()
                if lag < -1.0:
                    next_at = time.monotonic()
                await asyncio.sleep(max(0.0, lag))
        except SessionClosedError:
            rt.log("mic_stopped", reason="session_closed")
        except Exception as exc:
            self.fail("caller microphone", exc)
