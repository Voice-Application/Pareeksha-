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


class AudioV1Session(AudioSession):
    """One live ``pareeksha-audio-v1`` call. A background task turns frames into events."""

    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws
        self._events: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        self._closed = False
        self._ended = False
        #: Unknown or malformed agent text frames that were skipped (forward compatibility).
        self.ignored_messages = 0
        self._reader = asyncio.create_task(self._read_loop(), name="audio_v1-reader")

    async def _read_loop(self) -> None:
        reason = "transport_closed"
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    if message:
                        self._events.put_nowait(AgentAudio(message))
                    continue
                event = self._parse_text(message)
                if event is None:
                    continue
                self._events.put_nowait(event)
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
                self._events.put_nowait(AgentCallEnd(reason))
            self._events.put_nowait(None)

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
        self._events.put_nowait(None)


class AudioV1Adapter(Adapter):
    name: ClassVar[AdapterName] = "audio_v1"

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
        return AudioV1Session(ws)
