"""``audio_v1`` adapter: the native ``pareeksha-audio-v1`` WebSocket protocol (VOICE-04).

The platform is the WebSocket *client* (docs/06-api-spec.md section 7): connect, send the ``start``
text frame, then exchange 20 ms PCM s16le 16 kHz binary frames in both directions. The agent may
add JSON ``transcript`` / ``tool_call`` / ``call_end`` frames (glass box). This module only moves
frames; timing, VAD and recording live in ``pareeksha.simulation``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import ClassVar

from pydantic import ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from pareeksha.adapters.base import (
    Adapter,
    AdapterName,
    AgentAudio,
    AgentCallEnd,
    AgentConnectError,
    AgentEvent,
    AgentProtocolError,
    AgentTarget,
    AudioSession,
    CallContext,
    SessionClosedError,
    StartMessage,
    StopMessage,
    message_to_event,
    parse_agent_message,
)

log = logging.getLogger(__name__)

#: Largest WebSocket message accepted from an agent (a few seconds of audio at most).
MAX_MESSAGE_BYTES = 1 << 20

#: Backpressure: the reader blocks once this many undrained events are queued, so a peer that
#: floods frames faster than the pipeline consumes them cannot grow the queue without bound.
MAX_QUEUED_EVENTS = 256

#: Per-call hard budget on volume (not just time): an untrusted peer may stream frames far faster
#: than real time, so cap the total frames and bytes accepted. Generous for a legitimate call
#: (hours of 20 ms audio / well above a real transcript) but bounds a flooding peer. Exceeding
#: either ends the call with a protocol error.
MAX_TOTAL_FRAMES = 1_000_000
MAX_TOTAL_BYTES = 512 * 1024 * 1024


class AudioV1Session(AudioSession):
    """One live ``pareeksha-audio-v1`` call. A background task turns frames into events."""

    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws
        self._events: asyncio.Queue[AgentEvent | None] = asyncio.Queue(maxsize=MAX_QUEUED_EVENTS)
        self._closed = False
        self._ended = False
        #: Unknown or malformed agent text frames that were skipped (forward compatibility).
        self.ignored_messages = 0
        #: Per-call volume accounting for the hard budget (independent of the time watchdog).
        self._frames_seen = 0
        self._bytes_seen = 0
        self._reader = asyncio.create_task(self._read_loop(), name="audio_v1-reader")

    def _over_budget(self, message: bytes | str) -> bool:
        """Account one inbound frame; True once the per-call frame/byte budget is exceeded."""
        self._frames_seen += 1
        self._bytes_seen += len(message) if isinstance(message, (bytes, bytearray)) else len(
            message.encode("utf-8", "ignore")
        )
        return self._frames_seen > MAX_TOTAL_FRAMES or self._bytes_seen > MAX_TOTAL_BYTES

    async def _read_loop(self) -> None:
        reason = "transport_closed"
        try:
            async for message in self._ws:
                if self._over_budget(message):
                    raise AgentProtocolError(
                        "agent exceeded the per-call frame/byte budget"
                    )
                if isinstance(message, bytes):
                    for audio in self._on_binary(message):
                        # await (not put_nowait) so a flood is backpressured, not buffered unbounded
                        await self._events.put(audio)
                    continue
                event = self._parse_text(message)
                if event is None:
                    continue
                await self._events.put(event)
                if isinstance(event, AgentCallEnd):
                    self._ended = True
                    return
            reason = "completed" if self._ws.close_code == 1000 else reason
        except ConnectionClosed:
            pass
        except AgentProtocolError as exc:
            reason = f"protocol_error: {exc}"
        finally:
            if not self._ended and not self._closed:
                self._ended = True
                await self._events.put(AgentCallEnd(reason))
            await self._events.put(None)

    def _on_binary(self, data: bytes) -> list[AgentEvent]:
        """Turn one binary frame into events; subclasses may re-frame the audio."""
        return [AgentAudio(data)] if data else []

    def _parse_text(self, raw: str) -> AgentEvent | None:
        try:
            decoded = json.loads(raw)
        except ValueError as exc:
            raise AgentProtocolError("agent sent a text frame that is not JSON") from exc
        if not isinstance(decoded, dict):
            raise AgentProtocolError("agent text frames must be JSON objects")
        try:
            return message_to_event(parse_agent_message(raw))
        except ValidationError:
            self.ignored_messages += 1
            log.warning("ignored agent message of unknown type %r", decoded.get("type"))
            return None

    async def send_pcm16(self, frame: bytes) -> None:
        if self._closed:
            raise SessionClosedError("session is closed")
        try:
            await self._ws.send(frame)
        except ConnectionClosed as exc:
            raise SessionClosedError("agent closed the connection") from exc

    async def receive(self) -> AsyncIterator[AgentEvent]:
        while True:
            event = await self._events.get()
            if event is None:
                return
            yield event
            if isinstance(event, AgentCallEnd):
                return

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not self._ws.close_code:
            with contextlib.suppress(ConnectionClosed, WebSocketException, OSError):
                await self._ws.send(StopMessage().model_dump_json())
        with contextlib.suppress(ConnectionClosed, WebSocketException, OSError, TimeoutError):
            await asyncio.wait_for(self._ws.close(), timeout=2.0)
        self._reader.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._reader
        # Wake a waiting receive() with the sentinel; make room first since the queue is bounded.
        with contextlib.suppress(asyncio.QueueFull):
            self._events.put_nowait(None)


class AudioV1Adapter(Adapter):
    name: ClassVar[AdapterName] = "audio_v1"
    session_class: ClassVar[type[AudioV1Session]] = AudioV1Session

    async def connect(self, agent: AgentTarget, call_ctx: CallContext) -> AudioSession:
        start = StartMessage(
            call_id=str(call_ctx.call_id),
            language_hint=call_ctx.language_hint,
            metadata=dict(call_ctx.metadata),
        )
        try:
            ws = await asyncio.wait_for(
                connect(
                    agent.endpoint_url,
                    open_timeout=call_ctx.connect_timeout_s,
                    max_size=MAX_MESSAGE_BYTES,
                    compression=None,
                    ping_interval=20,
                ),
                timeout=call_ctx.connect_timeout_s + 1,
            )
        except (OSError, TimeoutError, WebSocketException, ValueError) as exc:
            raise AgentConnectError(
                f"cannot connect to {agent.endpoint_url}: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            await ws.send(start.model_dump_json(exclude_none=True))
        except (ConnectionClosed, OSError) as exc:
            raise AgentConnectError(f"agent closed during start: {exc}") from exc
        return self.session_class(ws)
