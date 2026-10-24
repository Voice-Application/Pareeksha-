"""In-process mock agent server + scripted caller for tests (fake STT/TTS, real WebSocket)."""

from __future__ import annotations

import array
import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from mock_agent.bugs import Bug
from mock_agent.server import CallSession, health_response
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.server import ServerConnection, serve

LOUD = array.array("h", [4000, -4000] * 160).tobytes()
QUIET = bytes(640)
TONE = array.array("h", [1000, -1000] * 160).tobytes()


class FakeSpeech:
    """Returns scripted STT text; TTS is a short tone whose length scales with the text."""

    def __init__(self, heard: list[str]) -> None:
        self.heard = list(heard)
        self.said: list[tuple[str, str]] = []

    async def hear(self, pcm16: bytes, language: str) -> str:
        return self.heard.pop(0) if self.heard else ""

    async def say(self, text: str, language: str) -> bytes:
        self.said.append((text, language))
        return TONE * 10  # 200 ms


@dataclass
class Recorder:
    audio_frames: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)

    def of(self, type_: str) -> list[dict[str, Any]]:
        return [m for m in self.messages if m["type"] == type_]


@contextlib.asynccontextmanager
async def running_agent(
    speech: FakeSpeech, bugs: frozenset[Bug] = frozenset()
) -> AsyncIterator[str]:
    async def handler(ws: ServerConnection) -> None:
        await CallSession(ws, speech, bugs).run()

    async with serve(handler, "127.0.0.1", 0, process_request=health_response) as server:
        port = next(iter(server.sockets)).getsockname()[1]
        yield f"127.0.0.1:{port}"


async def read_into(ws: ClientConnection, rec: Recorder) -> None:
    try:
        async for msg in ws:
            if isinstance(msg, bytes):
                rec.audio_frames += 1
            else:
                rec.messages.append(json.loads(msg))
    except Exception:  # connection closed by agent
        return


async def speak(ws: ClientConnection, speech_frames: int = 15, silence_frames: int = 45) -> None:
    for _ in range(speech_frames):
        await ws.send(LOUD)
    for _ in range(silence_frames):
        await ws.send(QUIET)


async def wait_for(predicate: Any, timeout: float = 5.0) -> None:
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.02)

    await asyncio.wait_for(poll(), timeout)


def start_message(language: str = "en-IN", **metadata: Any) -> str:
    return json.dumps(
        {
            "type": "start",
            "protocol": "pareeksha-audio-v1",
            "call_id": "11111111-1111-1111-1111-111111111111",
            "sample_rate": 16000,
            "language_hint": language,
            "metadata": metadata,
        }
    )


_READERS: set[asyncio.Task[None]] = set()


def start_reader(ws: ClientConnection, rec: Recorder) -> None:
    """Read the agent's frames in the background (the task reference is kept until done)."""
    task = asyncio.create_task(read_into(ws, rec))
    _READERS.add(task)
    task.add_done_callback(_READERS.discard)
