"""``audio_v1`` adapter and ``check_connection`` against real local WebSocket agents."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from websockets.asyncio.server import ServerConnection

from pareeksha.adapters.audio_v1 import AudioV1Adapter
from pareeksha.adapters.base import (
    AUDIO_FRAME_BYTES,
    AgentAudio,
    AgentCallEnd,
    AgentConnectError,
    AgentEvent,
    AgentTarget,
    AgentToolCall,
    AgentTranscript,
    CallContext,
    SessionClosedError,
)
from pareeksha.adapters.connection_check import check_connection
from pareeksha.adapters.registry import AdapterUnavailableError, available_adapters, get_adapter
from tests.integration.mock_agent_harness import FakeSpeech, running_agent
from tests.unit.simulation.simfakes import LOUD_FRAME, agent_server, read_start, send_tone

FRAME = bytes(AUDIO_FRAME_BYTES)


def target(url: str, **over: Any) -> AgentTarget:
    fields: dict[str, Any] = {
        "agent_id": uuid.uuid4(),
        "adapter": "audio_v1",
        "endpoint_url": url,
        "languages": ["kn-IN"],
    }
    return AgentTarget(**{**fields, **over})


def ctx(**over: Any) -> CallContext:
    return CallContext(call_id=uuid.uuid4(), language_hint="kn-IN", **over)


async def collect(session: Any) -> list[AgentEvent]:
    return [e async for e in session.receive()]


async def test_connect_sends_start_and_streams_audio_and_glass_box() -> None:
    seen: dict[str, Any] = {}

    async def agent(ws: ServerConnection) -> None:
        seen["start"] = await read_start(ws)
        await ws.send(json.dumps({"type": "transcript", "role": "agent", "text": "namaskara"}))
        await ws.send(LOUD_FRAME)
        await ws.send(json.dumps({"type": "future_message", "x": 1}))  # skipped, not fatal
        await ws.send(
            json.dumps({"type": "tool_call", "name": "t", "arguments": {"a": 1}, "result": {}})
        )
        await ws.send(json.dumps({"type": "call_end", "reason": "completed", "extra": True}))

    async with agent_server(agent) as url:
        call_ctx = ctx(metadata={"mock_bugs": ["no_disclosure"]})
        session = await AudioV1Adapter().connect(target(url), call_ctx)
        async with session:
            events = await collect(session)
    assert seen["start"]["protocol"] == "pareeksha-audio-v1"
    assert seen["start"]["call_id"] == str(call_ctx.call_id)
    assert seen["start"]["language_hint"] == "kn-IN" and seen["start"]["sample_rate"] == 16000
    assert seen["start"]["metadata"] == {"mock_bugs": ["no_disclosure"]}
    assert [type(e) for e in events] == [AgentTranscript, AgentAudio, AgentToolCall, AgentCallEnd]
    assert events[1].pcm16 == LOUD_FRAME  # type: ignore[union-attr]
    assert events[2].arguments == {"a": 1}  # type: ignore[union-attr]
    assert events[3].reason == "completed"  # type: ignore[union-attr]
    assert session.ignored_messages == 1  # type: ignore[attr-defined]


async def test_send_audio_reaches_the_agent_and_close_sends_stop() -> None:
    got: list[Any] = []

    async def agent(ws: ServerConnection) -> None:
        await read_start(ws)
        async for message in ws:
            got.append(message)

    async with agent_server(agent) as url:
        session = await AudioV1Adapter().connect(target(url), ctx())
        await session.send_pcm16(FRAME)
        await session.close()
        await session.close()  # idempotent
        with pytest.raises(SessionClosedError):
            await session.send_pcm16(FRAME)
        assert await collect(session) == []  # closed locally: no synthetic call end
        await asyncio.sleep(0.1)
    assert got[0] == FRAME
    assert json.loads(got[1]) == {"type": "stop", "reason": "caller_hangup"}


async def test_transport_close_without_call_end_becomes_agent_call_end() -> None:
    async def agent(ws: ServerConnection) -> None:
        await read_start(ws)
        await ws.send(LOUD_FRAME)
        await ws.close(code=1011)

    async with agent_server(agent) as url:
        session = await AudioV1Adapter().connect(target(url), ctx())
        events = await collect(session)
        await session.close()
    assert isinstance(events[0], AgentAudio)
    assert events[-1] == AgentCallEnd("transport_closed")


async def test_clean_close_reports_completed() -> None:
    async def agent(ws: ServerConnection) -> None:
        await read_start(ws)
        await ws.close(code=1000)

    async with agent_server(agent) as url:
        session = await AudioV1Adapter().connect(target(url), ctx())
        events = await collect(session)
        await session.close()
    assert events == [AgentCallEnd("completed")]


async def test_send_after_the_agent_hung_up_raises_session_closed() -> None:
    async def agent(ws: ServerConnection) -> None:
        await read_start(ws)
        await ws.close()

    async with agent_server(agent) as url:
        session = await AudioV1Adapter().connect(target(url), ctx())
        await collect(session)
        with pytest.raises(SessionClosedError):
            for _ in range(50):
                await session.send_pcm16(FRAME)
                await asyncio.sleep(0.01)
        await session.close()


async def test_text_frame_that_is_not_json_ends_the_call_with_a_protocol_error() -> None:
    async def agent(ws: ServerConnection) -> None:
        await read_start(ws)
        await ws.send("this is not json")
        await asyncio.sleep(0.5)

    async with agent_server(agent) as url:
        session = await AudioV1Adapter().connect(target(url), ctx())
        events = await collect(session)
        await session.close()
    assert len(events) == 1 and isinstance(events[0], AgentCallEnd)
    assert events[0].reason.startswith("protocol_error")


async def test_a_json_array_is_a_protocol_error_too() -> None:
    async def agent(ws: ServerConnection) -> None:
        await read_start(ws)
        await ws.send("[1, 2]")
        await asyncio.sleep(0.5)

    async with agent_server(agent) as url:
        session = await AudioV1Adapter().connect(target(url), ctx())
        events = await collect(session)
        await session.close()
    assert isinstance(events[0], AgentCallEnd) and "JSON objects" in events[0].reason


async def test_connect_failure_is_an_agent_connect_error() -> None:
    with pytest.raises(AgentConnectError, match="cannot connect"):
        await AudioV1Adapter().connect(target("ws://127.0.0.1:1/call"), ctx(connect_timeout_s=2))
    with pytest.raises(AgentConnectError):
        await AudioV1Adapter().connect(target("not a url"), ctx())


async def test_agent_closing_before_the_start_message_is_a_connect_failure_or_a_call_end() -> None:
    """Which one depends on whether our start frame wins the race with the agent's close."""

    async def agent(ws: ServerConnection) -> None:
        await ws.close()

    async with agent_server(agent) as url:
        await asyncio.sleep(0)
        try:
            session = await AudioV1Adapter().connect(target(url), ctx())
        except AgentConnectError as exc:
            assert "closed during start" in str(exc)
            return
        events = await collect(session)
        await session.close()
    assert isinstance(events[-1], AgentCallEnd)


def test_registry_knows_only_the_shipped_adapters() -> None:
    assert available_adapters() == ["audio_v1"]
    assert isinstance(get_adapter("audio_v1"), AudioV1Adapter)
    with pytest.raises(AdapterUnavailableError, match="pipecat"):
        get_adapter("pipecat")


# ------------------------------------------------------------------------------ test-connection


async def test_check_connection_ok_against_the_mock_agent() -> None:
    async with running_agent(FakeSpeech([])) as addr:
        result = await check_connection(target(f"ws://{addr}/call"), wait_s=5)
    assert result.ok and result.error is None
    assert result.protocol == "pareeksha-audio-v1"
    assert result.glass_box_messages_seen is True  # the mock agent sends its transcript first
    assert result.first_audio_ms is not None and result.first_audio_ms < 5000


async def test_check_connection_sends_one_second_of_silence() -> None:
    frames = 0

    async def agent(ws: ServerConnection) -> None:
        nonlocal frames
        await read_start(ws)
        await ws.send(LOUD_FRAME)  # audio straight away: no glass box
        async for message in ws:
            if isinstance(message, bytes) and not any(message):
                frames += 1

    async with agent_server(agent) as url:
        result = await check_connection(target(url), wait_s=3)
        await asyncio.sleep(0.2)
    assert result.ok and result.glass_box_messages_seen is False
    assert 1 <= frames <= 50  # the check stops as soon as it has seen audio


async def test_check_connection_times_out_when_the_agent_never_speaks() -> None:
    async def agent(ws: ServerConnection) -> None:
        await read_start(ws)
        await asyncio.sleep(5)

    async with agent_server(agent) as url:
        result = await check_connection(target(url), wait_s=0.5, silence_s=0.2)
    assert not result.ok and result.error == "timeout" and "0.5" in (result.detail or "")


async def test_check_connection_reports_connect_failures_and_unavailable_adapters() -> None:
    refused = await check_connection(target("ws://127.0.0.1:1/call"), connect_timeout_s=2)
    assert not refused.ok and refused.error == "connect_failed"
    other = await check_connection(target("ws://x/", adapter="vapi"))
    assert not other.ok and other.error == "adapter_unavailable"


async def test_check_connection_reports_an_agent_that_hangs_up() -> None:
    async def agent(ws: ServerConnection) -> None:
        await read_start(ws)
        await ws.send(json.dumps({"type": "call_end", "reason": "busy"}))
        await asyncio.sleep(0.5)

    async def silent_close(ws: ServerConnection) -> None:
        await read_start(ws)
        await ws.close()

    async with agent_server(agent) as url:
        ended = await check_connection(target(url), wait_s=3, silence_s=0.2)
    assert not ended.ok and ended.error == "closed" and "busy" in (ended.detail or "")
    async with agent_server(silent_close) as url:
        closed = await check_connection(target(url), wait_s=3, silence_s=0.2)
    assert not closed.ok and closed.error == "closed"


async def test_check_connection_streams_silence_while_agent_speaks_later() -> None:
    async def agent(ws: ServerConnection) -> None:
        await read_start(ws)
        await asyncio.sleep(0.3)
        await send_tone(ws, 0.1)

    async with agent_server(agent) as url:
        result = await check_connection(target(url), wait_s=3, silence_s=0.2)
    assert result.ok and result.first_audio_ms is not None and result.first_audio_ms >= 250
