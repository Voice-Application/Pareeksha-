"""The caller: when to answer, interrupt, nudge or hang up (FR-RN-4..6, TRD section 5 valves).

``CallerDirector`` sits between the caller-side STT and the caller TTS. It reacts to frames:

- an agent turn heard -> ask the caller brain for the next line and speak it (unless the agent was
  cut off by our own interruption, in which case we wait for its reply);
- the agent starts a turn -> maybe plan an interruption 0.8-2.5 s in (``BargeInScheduler``); the
  line is prepared right away and timed to start exactly then, or dropped if the agent finished;
- silence -> "Hello?" after 6 s of nothing at the start, one nudge after 8 s mid-call, then
  ``agent_silent``;
- end conditions: goal reached / gave up (brain), agent hangup, max turns, hard timeout.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

from pipecat.frames.frames import Frame, StartFrame
from pipecat.processors.frame_processor import FrameDirection

from pareeksha.llm.caller import HistoryLine
from pareeksha.schemas.calls import EndReason
from pareeksha.simulation.barge_in import BargeInPlan, BargeInScheduler
from pareeksha.simulation.frames import (
    AgentHangupFrame,
    AgentHeardFrame,
    AgentSpeechEndedFrame,
    AgentSpeechStartedFrame,
    AgentStreamEndedFrame,
    CallerSpeechEndedFrame,
    CallerSpeechStartedFrame,
    CancelSpeakFrame,
    SpeakKind,
    SpeakRequestFrame,
)
from pareeksha.simulation.models import BargeInAttempt
from pareeksha.simulation.processors import CallProcessor
from pareeksha.simulation.runtime import CallerLine, CallerSource, CallRuntime

log = logging.getLogger(__name__)

#: Scripted fallbacks for moments the brain is not asked about. Keyed by language prefix.
HELLO = {"en": "Hello?", "hi": "हैलो?", "kn": "ಹಲೋ?"}
NUDGE = {
    "en": "Hello, are you still there?",
    "hi": "हैलो, क्या आप सुन रहे हैं?",
    "kn": "ಹಲೋ, ನೀವು ಇನ್ನೂ ಇದ್ದೀರಾ?",
}
REPEAT = {
    "en": "Sorry, I could not hear that. Could you say it again?",
    "hi": "माफ़ कीजिए, मुझे सुनाई नहीं दिया। क्या आप दोबारा बोल सकते हैं?",
    "kn": "ಕ್ಷಮಿಸಿ, ನನಗೆ ಕೇಳಿಸಲಿಲ್ಲ. ದಯವಿಟ್ಟು ಮತ್ತೊಮ್ಮೆ ಹೇಳಿ.",
}
#: Wait for the agent's reply to our interruption this long after it stopped, before answering.
CUT_OFF_GRACE_MS = 400


def scripted(table: dict[str, str], language: str) -> str:
    return table.get(language.split("-")[0].lower(), table["en"])


@dataclass
class _Utterance:
    text: str
    kind: SpeakKind
    final: bool = False
    final_reason: EndReason = "goal_achieved"
    attempt: BargeInAttempt | None = None
    started: bool = False
    counts_as_turn: bool = False


class CallerDirector(CallProcessor):
    def __init__(self, rt: CallRuntime, source: CallerSource, barge: BargeInScheduler) -> None:
        super().__init__(rt, "CallerDirector")
        self._source = source
        self._barge = barge
        self._lang = rt.spec.language
        self.history: list[HistoryLine] = []
        self._utts: dict[int, _Utterance] = {}
        self._seq = 0
        self._epoch = 0
        self._agent_bursts = 0
        self._agent_speaking = False
        self._playing: int | None = None
        self._last_caller_start_ms = -1
        self._last_caller_end_ms = -1
        self._responding = False
        self._nudged = False
        self._finishing = False
        self._final_reason: EndReason = "goal_achieved"
        self._spoken_turns = 0
        self._unintelligible = 0
        self._silence: asyncio.Task[None] | None = None
        self._pending_barge: int | None = None
        self._agent_hung_up = False

    # ------------------------------------------------------------------ frame dispatch

    async def handle(self, frame: Frame, direction: FrameDirection) -> None:
        if direction is FrameDirection.UPSTREAM:
            if isinstance(frame, CallerSpeechStartedFrame):
                self._on_caller_started(frame)
            elif isinstance(frame, CallerSpeechEndedFrame):
                self._on_caller_ended(frame)
            else:
                await self.push_frame(frame, direction)
            return
        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            self._on_start()
            return
        if isinstance(frame, AgentSpeechStartedFrame):
            await self._on_agent_started(frame)
        elif isinstance(frame, AgentSpeechEndedFrame):
            await self._on_agent_ended(frame)
        elif isinstance(frame, AgentHeardFrame):
            self._on_heard(frame)
        elif isinstance(frame, AgentHangupFrame):
            self._agent_hung_up = True  # system frame: arrives before the last turn is heard
            self._cancel_silence()
        elif isinstance(frame, AgentStreamEndedFrame):
            self._on_stream_ended()
        await self.push_frame(frame, direction)

    # ------------------------------------------------------------------ lifecycle

    def _on_start(self) -> None:
        self.spawn(self._watchdog(), "watchdog")
        if self.rt.spec.scenario.caller_speaks_first:
            self._responding = True
            self.spawn(self._open(), "open")
        else:
            self._arm_silence(self.rt.settings.first_silence_s, opening=True)

    async def _watchdog(self) -> None:
        await asyncio.sleep(self.rt.spec.max_call_seconds)
        self.rt.finish("timeout")

    async def _open(self) -> None:
        """The scenario says the caller speaks first."""
        try:
            line = await self._next_line()
            self._responding = False
            await self._say_line(line, "reply")
        except Exception as exc:
            self.fail("caller brain", exc)

    # ------------------------------------------------------------------ agent events

    async def _on_agent_started(self, frame: AgentSpeechStartedFrame) -> None:
        self._agent_speaking = True
        self._nudged = False
        self._epoch += 1
        self._cancel_silence()
        number = self._agent_bursts
        self._agent_bursts += 1
        if self._playing is None and not self._finishing and not self._responding:
            plan = self._barge.plan(number)
            if plan is not None:
                self.spawn(self._prepare_barge(plan, frame.t_ms, self._epoch), "barge")

    async def _on_agent_ended(self, frame: AgentSpeechEndedFrame) -> None:
        self._agent_speaking = False
        uid = self._pending_barge
        if uid is not None:
            utt = self._utts[uid]
            if not utt.started:
                self._pending_barge = None
                if utt.attempt is not None:
                    utt.attempt.cancelled = True
                self.rt.log("barge_in_cancelled", utt_id=uid, reason="agent_stopped_first")
                await self.push_frame(CancelSpeakFrame(utt_id=uid))

    def _on_heard(self, frame: AgentHeardFrame) -> None:
        rt = self.rt
        rt.tracker.add_agent_turn(
            start_ms=frame.start_ms,
            end_ms=frame.end_ms,
            text=frame.text,
            confidence=frame.confidence,
            language=frame.language,
        )
        if frame.text:
            self.history.append(HistoryLine("agent", frame.text))
        if self._finishing or self._agent_hung_up or rt.finished.is_set():
            return
        if self._agent_speaking:
            return  # the agent went on talking: answer once that burst is heard too
        cut_off = self._playing is not None or (
            frame.start_ms < self._last_caller_end_ms
            and frame.end_ms <= self._last_caller_end_ms + CUT_OFF_GRACE_MS
        )
        if cut_off and not self._responding:
            # Our interruption stopped the agent: wait for its answer to it.
            self._arm_silence(rt.settings.mid_silence_s)
            return
        if self._responding:
            return
        if not frame.text:
            self._unintelligible += 1
            if self._unintelligible >= rt.settings.max_unintelligible:
                rt.finish(
                    "infra_error",
                    f"could not understand the agent {self._unintelligible} times in a row",
                )
                return
            self.spawn(self._ask_repeat(), "repeat")
            return
        self._unintelligible = 0
        if self._spoken_turns >= rt.spec.scenario.max_turns:
            rt.finish("max_turns")
            return
        self._responding = True
        self._cancel_silence()
        self.spawn(self._respond(self._epoch), "respond")

    def _on_stream_ended(self) -> None:
        self._cancel_silence()
        self.rt.finish(self._final_reason if self._finishing else "agent_hangup")

    # ------------------------------------------------------------------ caller events

    def _on_caller_started(self, frame: CallerSpeechStartedFrame) -> None:
        utt = self._utts.get(frame.utt_id)
        if utt is None:
            return
        utt.started = True
        self._playing = frame.utt_id
        self._last_caller_start_ms = frame.t_ms
        self._cancel_silence()
        if utt.attempt is not None:
            utt.attempt.started_ms = frame.t_ms
            utt.attempt.agent_speaking_at_start = self._agent_speaking
        if self._pending_barge == frame.utt_id:
            self._pending_barge = None
        if utt.counts_as_turn:
            self._spoken_turns += 1
        self.history.append(HistoryLine("caller", utt.text))
        self.rt.log(
            "caller_speech_start",
            t_ms=frame.t_ms,
            utt_id=frame.utt_id,
            kind=utt.kind,
            agent_speaking=self._agent_speaking,
        )

    def _on_caller_ended(self, frame: CallerSpeechEndedFrame) -> None:
        utt = self._utts.get(frame.utt_id)
        if utt is None:
            return
        self._playing = None
        self._last_caller_end_ms = frame.t_ms
        self.rt.tracker.add_caller_turn(
            start_ms=frame.start_ms or self._last_caller_start_ms,
            end_ms=frame.t_ms,
            ground_truth=utt.text,
            is_barge_in=utt.kind == "barge_in",
            kind=utt.kind,
        )
        self.rt.log("caller_speech_end", t_ms=frame.t_ms, utt_id=frame.utt_id, kind=utt.kind)
        if utt.final:
            self.spawn(self._finish_after_tail(utt.final_reason), "goodbye")
        elif not self._agent_speaking and not self._responding:
            self._arm_silence(self.rt.settings.mid_silence_s)

    async def _finish_after_tail(self, reason: EndReason) -> None:
        await asyncio.sleep(self.rt.settings.goodbye_tail_s)
        self.rt.finish(reason)

    # ------------------------------------------------------------------ speaking

    async def _next_line(self) -> CallerLine:
        line = await self._source.next_line(
            self.rt.spec.persona,
            self.rt.spec.scenario,
            list(self.history),
            self._spoken_turns + 1,
        )
        if line.usage is not None:
            self.rt.usage.append(line.usage)
        return line

    async def _speak(self, utt: _Utterance, *, play_at_ms: int | None = None) -> int:
        self._seq += 1
        uid = self._seq
        self._utts[uid] = utt
        await self.push_frame(
            SpeakRequestFrame(
                utt_id=uid, text=utt.text, kind=utt.kind, play_at_ms=play_at_ms, final=utt.final
            )
        )
        return uid

    async def _say_line(self, line: CallerLine, kind: SpeakKind) -> None:
        final_reason: EndReason = "goal_achieved"
        if line.end_call:
            # EVAL-01's reply carries no goal status: the caller gave up if its patience ran out.
            final_reason = (
                "gave_up"
                if self._spoken_turns + 1 >= self.rt.spec.persona.patience_turns
                else "goal_achieved"
            )
            self._finishing = True
            self._final_reason = final_reason
        await self._speak(
            _Utterance(
                line.utterance,
                kind,
                final=line.end_call,
                final_reason=final_reason,
                counts_as_turn=True,
            )
        )

    async def _respond(self, epoch: int) -> None:
        try:
            line = await self._next_line()
            delay = self._habit_delay()
            if delay:
                self.rt.log("caller_pause", seconds=round(delay, 2))
                await asyncio.sleep(delay)
            if self.rt.finished.is_set():
                return
            if epoch != self._epoch or self._agent_speaking:
                self.rt.log("caller_reply_dropped", reason="agent_spoke_again")
                self._responding = False
                return
            self._responding = False
            await self._say_line(line, "reply")
        except Exception as exc:
            self._responding = False
            self.fail("caller brain", exc)

    def _habit_delay(self) -> float:
        persona, s = self.rt.spec.persona, self.rt.settings
        rng = random.Random(f"habit:{self.rt.spec.seed}:{self._spoken_turns}")
        if persona.silence_habit == "long_pauses":
            return rng.uniform(*s.long_pause_s)
        if persona.silence_habit == "goes_silent" and rng.random() < s.goes_silent_probability:
            return s.goes_silent_s
        return 0.0

    async def _ask_repeat(self) -> None:
        await self._speak(_Utterance(scripted(REPEAT, self._lang), "repeat"))

    async def _prepare_barge(self, plan: BargeInPlan, start_ms: int, epoch: int) -> None:
        offset_ms = int(plan.offset_s * 1000)
        attempt = BargeInAttempt(
            agent_speech_start_ms=start_ms,
            planned_offset_ms=offset_ms,
            scheduled_ms=start_ms + offset_ms,
        )
        try:
            line = await self._next_line()
        except Exception as exc:  # an interruption is optional: never fail the call over it
            self.rt.log("barge_in_skipped", error=f"{type(exc).__name__}: {exc}")
            return
        self.rt.barge_attempts.append(attempt)
        if epoch != self._epoch or not self._agent_speaking or self._finishing or self._responding:
            attempt.cancelled = True
            self.rt.log("barge_in_cancelled", reason="agent_stopped_before_ready")
            return
        self.rt.log("barge_in_planned", scheduled_ms=attempt.scheduled_ms, offset_ms=offset_ms)
        uid = await self._speak(
            _Utterance(line.utterance, "barge_in", attempt=attempt, counts_as_turn=True),
            play_at_ms=attempt.scheduled_ms,
        )
        self._pending_barge = uid

    # ------------------------------------------------------------------ silence valves

    def _cancel_silence(self) -> None:
        task, self._silence = self._silence, None
        if task is not None and not task.done():
            task.cancel()

    def _arm_silence(self, seconds: float, *, opening: bool = False) -> None:
        self._cancel_silence()
        self._silence = self.spawn(self._silence_wait(seconds, opening), "silence")

    async def _silence_wait(self, seconds: float, opening: bool) -> None:
        await asyncio.sleep(seconds)
        if self._finishing or self._agent_speaking or self._playing is not None or self._responding:
            return
        if self._nudged:
            self.rt.finish("agent_silent")
            return
        self._nudged = True
        kind: SpeakKind = "hello" if opening else "nudge"
        table = HELLO if opening else NUDGE
        self.rt.log("silence_nudge", kind=kind, after_s=seconds)
        await self._speak(_Utterance(scripted(table, self._lang), kind))
