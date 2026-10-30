"""Inputs and outputs of one simulated call (docs/03-TRD.md section 5, FR-RN-4..8).

``CallResult`` carries what the ``simulator`` consumer (VOICE-05) persists: per-turn records
(FR-RN-8), glass-box tool calls, the timeline ``event_log``, the end reason (FR-RN-5), barge-in
attempts (FR-RN-6) and the three recordings (FR-RN-7).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from pareeksha.adapters.base import AgentTarget
from pareeksha.audio.profiles import LineProfile
from pareeksha.schemas.calls import EndReason, Speaker
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate


@dataclass(frozen=True)
class SimulationSettings:
    """Timing knobs. Defaults are the TRD section 5 valves; tests shrink them."""

    #: Agent silence that closes an agent turn (also the caller's reaction time floor).
    end_of_turn_s: float = 0.6
    vad_confidence: float = 0.7
    vad_start_s: float = 0.2
    #: Audio kept from before the VAD confirmed speech, so STT gets the word onset.
    preroll_ms: int = 300
    #: Shorter bursts are noise, not an agent turn.
    min_utterance_ms: int = 240
    #: No agent speech after connect: caller says "Hello?" after this long ...
    first_silence_s: float = 6.0
    #: ... and mid-call silence gets one nudge after this long, then ``agent_silent``.
    mid_silence_s: float = 8.0
    barge_in_min_s: float = 0.8
    barge_in_max_s: float = 2.5
    #: Quiet time sent after the caller's last word before the call is closed.
    goodbye_tail_s: float = 0.6
    #: ``long_pauses`` persona: extra pause before each reply.
    long_pause_s: tuple[float, float] = (1.5, 3.5)
    #: ``goes_silent`` persona: probability and length of a silent stretch before replying.
    goes_silent_probability: float = 0.25
    goes_silent_s: float = 10.0
    #: A caller line with nothing to speak (punctuation only, e.g. "...") is this long a stretch of
    #: real silence on the line; the TTS is not called for it.
    silent_turn_s: float = 5.0
    #: Agent turns STT could not read, in a row, before the call is abandoned as infra_error.
    max_unintelligible: int = 3
    #: How long to wait for the agent to start talking after the stop message at the very end.
    close_timeout_s: float = 3.0


@dataclass
class CallSpec:
    """Everything needed to run one call."""

    call_id: uuid.UUID
    agent: AgentTarget
    persona: PersonaCreate
    scenario: ScenarioCreate
    profile: LineProfile
    seed: int = 0
    max_call_seconds: int = 300
    #: Passed in the ``start`` message (e.g. ``{"mock_bugs": ["no_disclosure"]}``).
    metadata: dict[str, Any] = field(default_factory=dict)
    connect_timeout_s: float = 10.0

    @property
    def language(self) -> str:
        return self.persona.language


class TurnRecord(BaseModel):
    """One row of ``turns`` (docs/schema.sql). ``idx`` is the order of ``start_ms``."""

    idx: int
    speaker: Speaker
    #: Agent turns: caller-side STT of the agent. Caller turns: the ground-truth line.
    text: str
    start_ms: int
    end_ms: int
    ground_truth_text: str | None = None
    agent_heard_text: str | None = None
    #: Glass box only: what the agent says it said (``transcript`` role ``agent``).
    glass_box_text: str | None = None
    language_detected: str | None = None
    stt_confidence: float | None = None
    is_barge_in: bool = False
    #: Caller turns: why it was spoken (``reply``, ``barge_in``, ``hello``, ``nudge``, ``repeat``).
    kind: str | None = None


class ToolCallRecord(BaseModel):
    seq: int
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    at_ms: int
    turn_idx: int | None = None


class BargeInAttempt(BaseModel):
    """FR-RN-6: planned and actual time of one caller interruption."""

    agent_speech_start_ms: int
    planned_offset_ms: int
    scheduled_ms: int
    #: When the first interrupting audio frame left the platform (None = never played).
    started_ms: int | None = None
    #: The agent was still talking when the interruption started.
    agent_speaking_at_start: bool | None = None
    cancelled: bool = False


class CallEvent(BaseModel):
    """Timeline entry of ``calls.event_log``. ``t_ms`` is on the call's single monotonic clock."""

    t_ms: int
    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class RecordingFiles(BaseModel):
    caller: str
    agent: str
    mixed: str
    duration_ms: int


class UsageItem(BaseModel):
    """One billable external call, for ``api_usage`` and the credit log."""

    kind: Literal["stt", "tts", "llm"]
    provider: str
    operation: str
    audio_seconds: float = 0.0
    characters: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost: float | None = None
    latency_ms: int = 0
    cached: bool = False


class CallResult(BaseModel):
    call_id: uuid.UUID
    end_reason: EndReason
    duration_ms: int
    turns: list[TurnRecord] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    events: list[CallEvent] = Field(default_factory=list)
    barge_in_attempts: list[BargeInAttempt] = Field(default_factory=list)
    recordings: RecordingFiles | None = None
    usage: list[UsageItem] = Field(default_factory=list)
    #: Set with ``end_reason`` ``infra_error`` / ``connect_failed``.
    error: str | None = None
    #: The agent sent glass-box messages (transcripts or tool calls) during the call.
    glass_box: bool = False


class CallClock:
    """The call's single monotonic clock (milliseconds since the ``start`` message)."""

    def __init__(self) -> None:
        self._t0 = time.monotonic()

    def reset(self) -> None:
        self._t0 = time.monotonic()

    def now_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def now_s(self) -> float:
        return time.monotonic() - self._t0

    def to_monotonic(self, t_ms: float) -> float:
        return self._t0 + t_ms / 1000

    def since_monotonic(self, stamp: float) -> int:
        return int((stamp - self._t0) * 1000)
