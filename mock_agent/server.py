"""``pareeksha-audio-v1`` WebSocket server for the mock EMI agent (``python -m mock_agent.server``).

``GET /health`` answers the compose healthcheck; every other path upgrades to a call session.
Config: ``MOCK_BUGS`` (comma list of planted bugs), ``MOCK_AGENT_PORT`` (default 8765). A call's
``start.metadata["mock_bugs"]`` (list of names) overrides ``MOCK_BUGS`` for that call only.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import time
from typing import Any

from pareeksha.adapters.base import (
    AUDIO_FRAME_BYTES,
    AUDIO_FRAME_MS,
    CallEndMessage,
    StartMessage,
    ToolCallMessage,
    TranscriptMessage,
)
from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from mock_agent.bugs import Bug, bugs_from_env, parse_bugs
from mock_agent.policy import Dialog, Reply
from mock_agent.speech import GnaniAgentSpeech, Speech
from mock_agent.vad import UtteranceDetector

log = logging.getLogger("mock_agent")

MAX_CALL_S = 180
IDLE_TIMEOUT_S = 25
#: Speech frames needed while the agent is talking before it counts as a barge-in (120 ms).
BARGE_IN_FRAMES = 6


def health_response(connection: ServerConnection, request: Request) -> Response | None:
    if request.path == "/health":
        body = json.dumps(
            {"status": "ok", "agent": "mock-emi", "protocol": "pareeksha-audio-v1"}
        )
        return Response(
            200, "OK", Headers({"Content-Type": "application/json"}), body.encode()
        )
    return None


class CallSession:
    """One call: VAD -> STT -> scripted dialog -> TTS paced at real time, with glass-box events."""

    def __init__(
        self, ws: ServerConnection, speech: Speech, default_bugs: frozenset[Bug]
    ) -> None:
        self.ws = ws
        self.speech = speech
        self.bugs = default_bugs
        self.dialog = Dialog()
        self.t0 = time.monotonic()
        self.vad = UtteranceDetector()
        self.playing: asyncio.Task[None] | None = None
        self.utterances: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.barge_frames = 0
        self.ended = False
        self.opening_finished = False
        self.last_reply: Reply | None = None

    def now_ms(self) -> int:
        return int((time.monotonic() - self.t0) * 1000)

    async def _send(self, message: Any) -> None:
        await self.ws.send(message.model_dump_json(exclude_none=True))

    async def run(self) -> None:
        raw = await asyncio.wait_for(self.ws.recv(), timeout=IDLE_TIMEOUT_S)
        if isinstance(raw, bytes):
            return
        try:
            start = StartMessage.model_validate_json(raw)
        except ValidationError:
            await self.ws.close(code=1002, reason="expected start message")
            return
        override = start.metadata.get("mock_bugs")
        if override is not None:
            self.bugs = parse_bugs(override)
        self.t0 = time.monotonic()
        self.dialog = Dialog(language=start.language_hint or "en-IN", bugs=self.bugs)
        log.info(
            "call %s start lang=%s bugs=%s",
            start.call_id,
            self.dialog.language,
            sorted(self.bugs),
        )
        responder = asyncio.create_task(self._respond_loop())
        try:
            await self._start_playback(self.dialog.opening(), opening=True)
            await asyncio.wait_for(self._receive_loop(), timeout=MAX_CALL_S)
        except (TimeoutError, ConnectionClosed):
            pass
        finally:
            responder.cancel()
            await self._cancel_playback()
            with contextlib.suppress(ConnectionClosed):
                await self.ws.close()
            usage = getattr(self.speech, "usage_totals", None)
            if usage is not None:
                log.info("gnani usage (cumulative, uncached): %s", json.dumps(usage()))

    async def _receive_loop(self) -> None:
        async for msg in self.ws:
            if isinstance(msg, str):
                with contextlib.suppress(ValidationError):
                    if json.loads(msg).get("type") == "stop":
                        return
                continue
            if self.ended:
                return
            self._on_audio(msg)

    def _on_audio(self, frame: bytes) -> None:
        playing = self.playing is not None and not self.playing.done()
        if playing and Bug.IGNORE_INTERRUPT in self.bugs:
            return  # bug 4: VAD is off while the agent talks; interruptions are never heard
        utterance = self.vad.feed(frame)
        if playing:
            self.barge_frames = self.barge_frames + 1 if self.vad.speaking else 0
            if self.barge_frames >= BARGE_IN_FRAMES and self.playing is not None:
                self.playing.cancel()  # barge-in: stop talking immediately
        else:
            self.barge_frames = 0
        if utterance is not None:
            self.utterances.put_nowait(utterance)

    async def _respond_loop(self) -> None:
        while True:
            utterance = await self.utterances.get()
            if utterance is None:
                return
            if self.dialog.stage == "done" and self.last_reply is not None:
                # The agent already ended the call: never talk over its goodbye; if the caller cut it off,
                # say the same goodbye again (its tool calls were already reported).
                if self.playing is None or self.playing.done():
                    await self._start_playback(
                        dataclasses.replace(self.last_reply, tool_calls=())
                    )
                continue
            try:
                heard = await self.speech.hear(utterance, self.dialog.language)
            except Exception:
                log.exception(
                    "speech-to-text failed; treating the utterance as not heard"
                )
                heard = ""
            await self._send(
                TranscriptMessage(role="user", text=heard, t_ms=self.now_ms())
            )
            replaying = not self.opening_finished
            if replaying:
                self.dialog.opening_cut = (
                    True  # the caller spoke over the disclosure: say it again
                )
            reply = self.dialog.respond(heard)
            await self._cancel_playback()
            await self._start_playback(reply, opening=replaying)

    async def _cancel_playback(self) -> None:
        task = self.playing
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _start_playback(self, reply: Reply, opening: bool = False) -> None:
        self.playing = asyncio.create_task(self._speak(reply, opening))

    async def _speak(self, reply: Reply, opening: bool = False) -> None:
        self.last_reply = reply
        await self._send(
            TranscriptMessage(role="agent", text=reply.text, t_ms=self.now_ms())
        )
        try:
            pcm = await self.speech.say(reply.text, reply.language)
            await self._stream_pcm(pcm)
            if opening:
                self.opening_finished = True
        finally:
            # The tool call was decided with the reply; a caller who talks over the reply (which
            # cancels this task) must not make the agent forget it.
            for name, arguments, result in reply.tool_calls:
                await self._send(
                    ToolCallMessage(
                        name=name,
                        arguments=arguments,
                        result=result,
                        t_ms=self.now_ms(),
                    )
                )
        if reply.end_call:
            self.ended = True
            await self._send(CallEndMessage(reason="completed"))
            await self.ws.close()

    async def _stream_pcm(self, pcm: bytes) -> None:
        next_at = time.monotonic()
        for i in range(0, len(pcm), AUDIO_FRAME_BYTES):
            frame = pcm[i : i + AUDIO_FRAME_BYTES].ljust(AUDIO_FRAME_BYTES, b"\x00")
            await self.ws.send(frame)
            next_at += AUDIO_FRAME_MS / 1000
            await asyncio.sleep(max(0.0, next_at - time.monotonic()))


async def serve_forever(
    host: str = "0.0.0.0", port: int = 8765, speech: Speech | None = None
) -> None:
    engine = speech or GnaniAgentSpeech()
    default_bugs = bugs_from_env()

    async def handler(ws: ServerConnection) -> None:
        await CallSession(ws, engine, default_bugs).run()

    async with serve(
        handler, host, port, process_request=health_response, max_size=2**20
    ):
        log.info("mock agent on :%d bugs=%s", port, sorted(default_bugs))
        await asyncio.Future()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(serve_forever(port=int(os.environ.get("MOCK_AGENT_PORT", "8765"))))


if __name__ == "__main__":
    main()
