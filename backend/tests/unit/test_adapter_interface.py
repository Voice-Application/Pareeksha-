"""Interface tests for adapters/base.py (AudioSession, Adapter, pareeksha-audio-v1 messages)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic import ValidationError

from pareeksha.adapters.base import (
    AUDIO_FRAME_BYTES,
    AUDIO_SAMPLE_RATE,
    PROTOCOL,
    Adapter,
    AgentAudio,
    AgentCallEnd,
    AgentConnectError,
    AgentEvent,
    AgentTarget,
    AgentToolCall,
    AgentTranscript,
    AudioSession,
    CallContext,
    SessionClosedError,
    StartMessage,
    StopMessage,
    message_to_event,
    parse_agent_message,
)


class LoopbackSession(AudioSession):
    """Echo agent used only to exercise the interface."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.closed = False
        self.close_calls = 0

    async def send_pcm16(self, frame: bytes) -> None:
        if self.closed:
            raise SessionClosedError("closed")
        self.sent.append(frame)

    async def receive(self) -> AsyncIterator[AgentEvent]:
        yield AgentTranscript("agent", "hello", t_ms=10)
        for frame in self.sent:
            yield AgentAudio(frame)
        yield AgentCallEnd("completed")

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class LoopbackAdapter(Adapter):
    name = "audio_v1"

    async def connect(self, agent: AgentTarget, call_ctx: CallContext) -> AudioSession:
        if agent.endpoint_url.startswith("ws://unreachable"):
            raise AgentConnectError("refused")
        return LoopbackSession()


def target(url: str = "ws://mock-agent:8765/ws") -> AgentTarget:
    return AgentTarget(agent_id=uuid.uuid4(), adapter="audio_v1", endpoint_url=url)


def test_constants_match_the_protocol() -> None:
    assert PROTOCOL == "pareeksha-audio-v1"
    assert AUDIO_SAMPLE_RATE == 16000
    assert AUDIO_FRAME_BYTES == 640  # 20 ms of 16-bit mono at 16 kHz


def test_abstract_classes_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        AudioSession()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        Adapter()  # type: ignore[abstract]


def test_incomplete_subclasses_cannot_be_instantiated() -> None:
    class NoClose(AudioSession):
        async def send_pcm16(self, frame: bytes) -> None: ...

        async def receive(self) -> AsyncIterator[AgentEvent]:
            yield AgentCallEnd()

    class NoConnect(Adapter):
        name = "audio_v1"

    with pytest.raises(TypeError, match="close"):
        NoClose()  # type: ignore[abstract]
    with pytest.raises(TypeError, match="connect"):
        NoConnect()  # type: ignore[abstract]


async def test_session_round_trip_and_context_manager() -> None:
    adapter = LoopbackAdapter()
    ctx = CallContext(call_id=uuid.uuid4(), language_hint="kn-IN")
    async with await adapter.connect(target(), ctx) as session:
        assert isinstance(session, LoopbackSession)
        await session.send_pcm16(b"\x00" * AUDIO_FRAME_BYTES)
        events = [event async for event in session.receive()]
    assert isinstance(events[0], AgentTranscript)
    assert events[1] == AgentAudio(b"\x00" * AUDIO_FRAME_BYTES)
    assert events[-1] == AgentCallEnd("completed")
    assert session.closed and session.close_calls == 1
    with pytest.raises(SessionClosedError):
        await session.send_pcm16(b"")


async def test_connect_failure_is_an_adapter_error() -> None:
    adapter = LoopbackAdapter()
    with pytest.raises(AgentConnectError):
        await adapter.connect(target("ws://unreachable:1/ws"), CallContext(call_id=uuid.uuid4()))


def test_adapter_name_is_a_class_attribute() -> None:
    assert LoopbackAdapter.name == "audio_v1"


def test_agent_target_and_context_validation() -> None:
    with pytest.raises(ValidationError):
        AgentTarget(agent_id=uuid.uuid4(), adapter="twilio", endpoint_url="x")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        CallContext(call_id=uuid.uuid4(), connect_timeout_s=0)
    secret_target = AgentTarget(
        agent_id=uuid.uuid4(),
        adapter="vapi",
        endpoint_url="asst_1",
        adapter_secrets={"k": "s3cret"},
    )
    assert "s3cret" not in repr(secret_target)


def test_start_and_stop_messages() -> None:
    start = StartMessage(call_id="c1", language_hint="kn-IN")
    assert start.model_dump(mode="json") == {
        "type": "start",
        "protocol": "pareeksha-audio-v1",
        "call_id": "c1",
        "sample_rate": 16000,
        "language_hint": "kn-IN",
        "metadata": {},
    }
    assert StopMessage().model_dump()["reason"] == "caller_hangup"
    with pytest.raises(ValidationError):
        StartMessage(call_id="c1", sample_rate=8000)  # type: ignore[arg-type]


def test_parse_agent_messages() -> None:
    transcript = parse_agent_message(
        '{"type":"transcript","role":"user","text":"naal-ku saavira","is_final":true,"t_ms":9450}'
    )
    assert message_to_event(transcript) == AgentTranscript("user", "naal-ku saavira", True, 9450)

    tool = parse_agent_message(
        b'{"type":"tool_call","name":"record_promise_to_pay","arguments":{"amount":40000},'
        b'"result":{"ok":true},"t_ms":11200}'
    )
    assert message_to_event(tool) == AgentToolCall(
        "record_promise_to_pay", {"amount": 40000}, {"ok": True}, 11200
    )

    assert message_to_event(parse_agent_message('{"type":"call_end","reason":"completed"}')) == (
        AgentCallEnd("completed")
    )
    assert message_to_event(parse_agent_message('{"type":"stop"}')) == AgentCallEnd("caller_hangup")


def test_agents_may_add_unknown_fields_but_not_unknown_types() -> None:
    parsed = parse_agent_message('{"type":"call_end","vendor_field":1}')
    assert message_to_event(parsed) == AgentCallEnd("completed")
    with pytest.raises(ValidationError):
        parse_agent_message('{"type":"banana"}')
    with pytest.raises(ValidationError):
        parse_agent_message('{"type":"transcript","role":"robot","text":"x"}')
    with pytest.raises(ValidationError):
        parse_agent_message("not json")
