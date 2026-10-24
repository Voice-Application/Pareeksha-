"""Agent session interface and the ``pareeksha-audio-v1`` protocol messages.

FROZEN CONTRACT (docs/10-integrations-and-dx.md section 4, docs/06-api-spec.md section 7,
AGENTS.md 6.4). Every adapter (``audio_v1``, ``pipecat``, ``livekit``, ``vapi``) exposes the same
internal interface to the simulator: ``Adapter.connect(agent, call_ctx) -> AudioSession`` with
``send_pcm16(frame)``, ``receive()`` (audio frames plus optional glass-box events) and ``close()``.
The rest of the platform only sees these semantics, never the vendor transport.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import TracebackType
from typing import Annotated, Any, ClassVar, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL: Final = "pareeksha-audio-v1"
AUDIO_SAMPLE_RATE: Final = 16_000
AUDIO_FRAME_MS = 20
#: 16-bit mono PCM: 16000 Hz * 0.020 s * 2 bytes.
AUDIO_FRAME_BYTES = AUDIO_SAMPLE_RATE * AUDIO_FRAME_MS // 1000 * 2

AdapterName = Literal["audio_v1", "pipecat", "livekit", "vapi"]


class AdapterError(Exception):
    """Base class for adapter failures."""


class AgentConnectError(AdapterError):
    """The agent could not be reached or never started. Retryable (retry topics, then DLQ)."""


class AgentProtocolError(AdapterError):
    """The agent sent something the adapter cannot interpret."""


class SessionClosedError(AdapterError):
    """``send_pcm16`` or ``receive`` used after ``close()``."""


# ---------------------------------------------------------------------------------------------
# Events yielded by AudioSession.receive()
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentAudio:
    """Agent audio: raw PCM s16le mono 16 kHz, normally one 20 ms frame (640 bytes)."""

    pcm16: bytes


@dataclass(frozen=True, slots=True)
class AgentTranscript:
    """Glass-box: what the agent's own STT heard (role ``user``) or is about to say (``agent``)."""

    role: Literal["user", "agent"]
    text: str
    is_final: bool = True
    t_ms: int | None = None


@dataclass(frozen=True, slots=True)
class AgentToolCall:
    """Glass-box: a tool the agent invoked."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    t_ms: int | None = None


@dataclass(frozen=True, slots=True)
class AgentCallEnd:
    """The agent ended the call (``call_end`` message, ``stop``, or the transport closed)."""

    reason: str = "completed"


AgentEvent = AgentAudio | AgentTranscript | AgentToolCall | AgentCallEnd


# ---------------------------------------------------------------------------------------------
# pareeksha-audio-v1 text frames (JSON with a ``type`` field)
# ---------------------------------------------------------------------------------------------


class _Msg(BaseModel):
    model_config = ConfigDict(extra="ignore")  # agents may add fields; the platform ignores them


class StartMessage(_Msg):
    """Platform -> agent, first text frame."""

    type: Literal["start"] = "start"
    protocol: Literal["pareeksha-audio-v1"] = PROTOCOL
    call_id: str
    sample_rate: Literal[16000] = AUDIO_SAMPLE_RATE
    language_hint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StopMessage(_Msg):
    """Platform -> agent (or agent -> platform) to end the call."""

    type: Literal["stop"] = "stop"
    reason: str = "caller_hangup"


class TranscriptMessage(_Msg):
    """Agent -> platform, optional glass-box transcript."""

    type: Literal["transcript"] = "transcript"
    role: Literal["user", "agent"]
    text: str
    is_final: bool = True
    t_ms: int | None = None


class ToolCallMessage(_Msg):
    """Agent -> platform, optional glass-box tool call."""

    type: Literal["tool_call"] = "tool_call"
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    t_ms: int | None = None


class CallEndMessage(_Msg):
    """Agent -> platform: the agent ended the call."""

    type: Literal["call_end"] = "call_end"
    reason: str = "completed"


AgentMessage = Annotated[
    TranscriptMessage | ToolCallMessage | CallEndMessage | StopMessage,
    Field(discriminator="type"),
]
_AGENT_MESSAGE_ADAPTER: TypeAdapter[AgentMessage] = TypeAdapter(AgentMessage)


def parse_agent_message(raw: str | bytes) -> AgentMessage:
    """Parse one agent -> platform text frame. Raises pydantic ``ValidationError`` if invalid."""
    return _AGENT_MESSAGE_ADAPTER.validate_json(raw)


def message_to_event(message: AgentMessage) -> AgentEvent:
    """Map an agent text frame to the event yielded by ``AudioSession.receive``."""
    if isinstance(message, TranscriptMessage):
        return AgentTranscript(message.role, message.text, message.is_final, message.t_ms)
    if isinstance(message, ToolCallMessage):
        return AgentToolCall(message.name, message.arguments, message.result, message.t_ms)
    if isinstance(message, CallEndMessage):
        return AgentCallEnd(message.reason)
    return AgentCallEnd(message.reason)  # StopMessage from the agent side


# ---------------------------------------------------------------------------------------------
# Session and adapter interfaces
# ---------------------------------------------------------------------------------------------


class AgentTarget(BaseModel):
    """The agent under test, as an adapter sees it (a projection of the ``agents`` row)."""

    model_config = ConfigDict(extra="forbid")

    agent_id: uuid.UUID
    adapter: AdapterName
    endpoint_url: str
    adapter_config: dict[str, Any] = Field(default_factory=dict)
    #: Decrypted adapter secrets (e.g. a Vapi API key). Never logged.
    adapter_secrets: dict[str, str] = Field(default_factory=dict, repr=False)
    languages: list[str] = Field(default_factory=list)
    glass_box: bool = False


class CallContext(BaseModel):
    """Per-call data an adapter needs to open a session."""

    model_config = ConfigDict(extra="forbid")

    call_id: uuid.UUID
    language_hint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    connect_timeout_s: float = Field(default=10.0, gt=0)


class AudioSession(ABC):
    """One live call with an agent under test.

    Audio is raw PCM s16le mono 16 kHz in both directions (20 ms frames, real-time pace).
    Use as ``async with`` so ``close`` always runs.
    """

    @abstractmethod
    async def send_pcm16(self, frame: bytes) -> None:
        """Send caller audio to the agent. Raises ``SessionClosedError`` after ``close``."""

    @abstractmethod
    def receive(self) -> AsyncIterator[AgentEvent]:
        """Async iterator of agent audio frames and glass-box events.

        Ends (after yielding ``AgentCallEnd`` if the agent announced one) when the agent hangs up,
        the transport closes, or ``close`` is called. Implementations are async generators.
        """

    @abstractmethod
    async def close(self) -> None:
        """Hang up and release the transport. Idempotent."""

    async def __aenter__(self) -> AudioSession:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()


class Adapter(ABC):
    """Factory for sessions of one adapter kind."""

    name: ClassVar[AdapterName]

    @abstractmethod
    async def connect(self, agent: AgentTarget, call_ctx: CallContext) -> AudioSession:
        """Open a session. Raises ``AgentConnectError`` if the agent cannot be reached."""
