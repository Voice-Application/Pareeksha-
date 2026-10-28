"""Frames that travel through the caller pipeline, on top of Pipecat's ``Frame`` classes.

Everything that carries a time carries ``t_ms`` on the call clock, stamped where the event
happened (the source or the microphone), never where it was handled. Queueing delay in a slow
processor (STT, LLM) therefore cannot distort the recorded timeline.

System frames jump the processor queues, so speech-activity and glass-box events are never held
up behind a long STT or LLM call. Data frames stay in order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pipecat.frames.frames import DataFrame, SystemFrame

# --------------------------------------------------------------------------- agent -> caller


@dataclass
class AgentSpeechStartedFrame(SystemFrame):
    t_ms: int = 0


@dataclass
class AgentSpeechEndedFrame(SystemFrame):
    start_ms: int = 0
    t_ms: int = 0


@dataclass
class AgentTranscriptFrame(SystemFrame):
    role: Literal["user", "agent"] = "agent"
    text: str = ""
    is_final: bool = True
    t_ms: int = 0


@dataclass
class AgentToolCallFrame(SystemFrame):
    #: Not ``name``: that is Pipecat's own frame-name field.
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    t_ms: int = 0


@dataclass
class AgentHangupFrame(SystemFrame):
    reason: str = "completed"
    t_ms: int = 0


@dataclass
class AgentUtteranceFrame(DataFrame):
    """One agent turn of audio (pre-roll included) for caller-side STT."""

    pcm: bytes = field(default=b"", repr=False)
    start_ms: int = 0
    end_ms: int = 0


@dataclass
class AgentHeardFrame(DataFrame):
    """What the caller's STT made of an agent turn (``text`` empty = unintelligible / STT error)."""

    text: str = ""
    start_ms: int = 0
    end_ms: int = 0
    confidence: float | None = None
    language: str | None = None
    stt_failed: bool = False


@dataclass
class AgentStreamEndedFrame(DataFrame):
    """Pushed after the last utterance when the agent hangs up: nothing more will arrive."""

    reason: str = "completed"
    t_ms: int = 0


# --------------------------------------------------------------------------- caller -> agent

SpeakKind = Literal["reply", "barge_in", "hello", "nudge", "repeat"]


@dataclass
class SpeakRequestFrame(DataFrame):
    """Ask the TTS to voice ``text``; the microphone plays it at ``play_at_ms`` (None = now)."""

    utt_id: int = 0
    text: str = ""
    kind: SpeakKind = "reply"
    play_at_ms: int | None = None
    #: The last thing the caller says; the call ends once it has been played.
    final: bool = False


@dataclass
class CallerSpeechFrame(DataFrame):
    """Synthesised caller speech (clean, 16 kHz mono PCM) on its way to the microphone."""

    utt_id: int = 0
    text: str = ""
    kind: SpeakKind = "reply"
    pcm: bytes = field(default=b"", repr=False)
    play_at_ms: int | None = None
    final: bool = False
    #: A long line arrives in parts (first sentence, rest); the microphone plays them back to back.
    last_part: bool = True


@dataclass
class CancelSpeakFrame(SystemFrame):
    """Drop a queued utterance that has not started playing."""

    utt_id: int = 0


@dataclass
class CallerSpeechStartedFrame(SystemFrame):
    """Pushed upstream by the microphone when the first speech frame of an utterance is sent."""

    utt_id: int = 0
    t_ms: int = 0


@dataclass
class CallerSpeechEndedFrame(SystemFrame):
    """Pushed upstream by the microphone when the last speech frame of an utterance is sent."""

    utt_id: int = 0
    t_ms: int = 0
    start_ms: int = 0
