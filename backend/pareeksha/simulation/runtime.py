"""Shared per-call state and the caller-brain port.

Pipecat processors only talk to their neighbours through frames. What they all need to agree on
(the clock, the recorder, the event log, how the call ends) lives here, in one object that the
runner builds per call.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pareeksha.llm.caller import CallerBrain, HistoryLine
from pareeksha.schemas.calls import EndReason
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate
from pareeksha.simulation.models import (
    BargeInAttempt,
    CallClock,
    CallEvent,
    CallSpec,
    SimulationSettings,
    UsageItem,
)
from pareeksha.simulation.recorder import AudioRecorder
from pareeksha.simulation.turn_tracker import TurnTracker

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallerLine:
    """What the caller brain decided to say next."""

    utterance: str
    end_call: bool = False
    usage: UsageItem | None = None


class CallerSource(Protocol):
    """Produces the caller's next line from persona, scenario and the dialogue so far."""

    async def next_line(
        self,
        persona: PersonaCreate,
        scenario: ScenarioCreate,
        history: Sequence[HistoryLine],
        turn_number: int,
    ) -> CallerLine: ...


class BrainCallerSource:
    """``CallerSource`` backed by ``CallerBrain`` (EVAL-01: ``caller_v1.j2`` + the LLM client)."""

    def __init__(self, brain: CallerBrain) -> None:
        self._brain = brain

    async def next_line(
        self,
        persona: PersonaCreate,
        scenario: ScenarioCreate,
        history: Sequence[HistoryLine],
        turn_number: int,
    ) -> CallerLine:
        result = await self._brain.next_utterance(
            persona, scenario, history, turn_number=turn_number
        )
        cached = result.cache_hit
        usage = UsageItem(
            kind="llm",
            provider=result.provider.value,
            operation="llm_caller",
            input_tokens=0 if cached else result.usage.input_tokens,
            output_tokens=0 if cached else result.usage.output_tokens,
            est_cost=result.est_cost,
            latency_ms=result.latency_ms,
            cached=cached,
        )
        return CallerLine(result.parsed.utterance, result.parsed.end_call, usage)


class CallRuntime:
    """One call's clock, recorder, turn bookkeeping, event log and end signal."""

    def __init__(self, spec: CallSpec, settings: SimulationSettings, clock: CallClock) -> None:
        self.spec = spec
        self.settings = settings
        self.clock = clock
        self.recorder = AudioRecorder()
        self.tracker = TurnTracker()
        self.events: list[CallEvent] = []
        self.usage: list[UsageItem] = []
        self.barge_attempts: list[BargeInAttempt] = []
        #: Source -> tap time of every agent audio frame: the pipeline's own overhead (NFR-2).
        self.hop_ms: list[float] = []
        self.finished = asyncio.Event()
        self.end_reason: EndReason | None = None
        self.error: str | None = None
        self.ended_ms: int | None = None

    def log(self, type_: str, t_ms: int | None = None, **data: Any) -> None:
        self.events.append(
            CallEvent(t_ms=self.clock.now_ms() if t_ms is None else t_ms, type=type_, data=data)
        )

    def finish(self, reason: EndReason, error: str | None = None) -> None:
        """End the call (first caller wins). Safe from any task."""
        if self.finished.is_set():
            return
        self.end_reason = reason
        self.error = error
        self.ended_ms = self.clock.now_ms()
        self.log("call_end", reason=reason, error=error)
        self.finished.set()
