"""``POST /agents/{id}/test-connection``: open the socket, send 1 s of silence, wait for audio.

Docs/06-api-spec.md section 1: success needs agent audio within ``wait_s`` (10 s) after the first
byte of silence; glass-box messages seen on the way are reported.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid

from pareeksha.adapters.base import (
    AUDIO_FRAME_BYTES,
    AUDIO_FRAME_MS,
    PROTOCOL,
    AdapterError,
    AgentAudio,
    AgentCallEnd,
    AgentConnectError,
    AgentTarget,
    AgentToolCall,
    AgentTranscript,
    CallContext,
    SessionClosedError,
)
from pareeksha.adapters.registry import get_adapter
from pareeksha.schemas.agents import TestConnectionResult

SILENCE_SECONDS = 1.0
WAIT_FOR_AUDIO_S = 10.0


async def check_connection(
    agent: AgentTarget,
    *,
    language_hint: str | None = None,
    silence_s: float = SILENCE_SECONDS,
    wait_s: float = WAIT_FOR_AUDIO_S,
    connect_timeout_s: float = 10.0,
) -> TestConnectionResult:
    try:
        adapter = get_adapter(agent.adapter)
        ctx = CallContext(
            call_id=uuid.uuid4(),
            language_hint=language_hint or (agent.languages[0] if agent.languages else None),
            metadata={"test_connection": True},
            connect_timeout_s=connect_timeout_s,
        )
        session = await adapter.connect(agent, ctx)
    except AgentConnectError as exc:
        return TestConnectionResult(ok=False, error="connect_failed", detail=str(exc))
    except AdapterError as exc:
        return TestConnectionResult(ok=False, error="adapter_unavailable", detail=str(exc))

    glass_box = False
    started = time.monotonic()
    first_audio_ms: int | None = None
    error: str | None = None
    detail: str | None = None

    async def feed_silence() -> None:
        frame = bytes(AUDIO_FRAME_BYTES)
        next_at = time.monotonic()
        for _ in range(int(silence_s * 1000 / AUDIO_FRAME_MS)):
            await session.send_pcm16(frame)
            next_at += AUDIO_FRAME_MS / 1000
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))

    async def wait_for_audio() -> None:
        nonlocal glass_box, first_audio_ms, error, detail
        async for event in session.receive():
            if isinstance(event, AgentAudio):
                first_audio_ms = int((time.monotonic() - started) * 1000)
                return
            if isinstance(event, AgentTranscript | AgentToolCall):
                glass_box = True
            elif isinstance(event, AgentCallEnd):
                error = "closed"
                detail = f"agent ended the call before sending audio: {event.reason}"
                return

    sender = asyncio.create_task(feed_silence())
    try:
        async with session:
            await asyncio.wait_for(wait_for_audio(), timeout=wait_s)
            if error is None and first_audio_ms is None:
                error, detail = "closed", "agent closed the connection before sending audio"
    except TimeoutError:
        error, detail = "timeout", f"no agent audio within {wait_s:g} s"
    except SessionClosedError:
        error, detail = "closed", "agent closed the connection while receiving silence"
    except AdapterError as exc:
        error, detail = "protocol_error", str(exc)
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, SessionClosedError):
            await sender

    if error is not None:
        return TestConnectionResult(
            ok=False, error=error, detail=detail, glass_box_messages_seen=glass_box
        )
    return TestConnectionResult(
        ok=True,
        first_audio_ms=first_audio_ms,
        protocol=PROTOCOL,
        glass_box_messages_seen=glass_box,
    )
