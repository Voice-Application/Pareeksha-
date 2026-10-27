"""Adapter contract (FR-DX-7): ``audio_v1`` and the Pipecat example bot behave identically.

Both agents are real WebSocket servers reached through the production adapters. The Pipecat bot is
``examples/pipecat-bot/bot.py`` (real transport, serializer, VAD, aggregators, glass-box
processor); only its STT/LLM/TTS services are scripted so the contract run needs no network.
"""

from __future__ import annotations

import array
import asyncio
import contextlib
import importlib.util
import sys
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from pipecat.audio.vad.vad_analyzer import VADAnalyzer
from pipecat.frames.frames import (
    Frame,
    FunctionCallResultFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService

from pareeksha.adapters.audio_v1 import AudioV1Adapter
from pareeksha.adapters.base import (
    AUDIO_FRAME_BYTES,
    Adapter,
    AdapterName,
    AgentAudio,
    AgentEvent,
    AgentTarget,
    AgentToolCall,
    AgentTranscript,
    AudioSession,
    CallContext,
)
from pareeksha.adapters.pipecat_adapter import PipecatAdapter
from pareeksha.adapters.pipecat_serializer import PareekshaFrameSerializer
from tests.integration.mock_agent_harness import FakeSpeech, running_agent

REPO = Path(__file__).resolve().parents[3]
LOUD = array.array("h", [4000, -4000] * 160).tobytes()
QUIET = bytes(AUDIO_FRAME_BYTES)
TONE = array.array("h", [3000, -3000] * 800).tobytes()  # 100 ms at 16 kHz


def load_bot() -> Any:
    path = REPO / "examples" / "pipecat-bot"
    sys.path.insert(0, str(path))
    try:
        spec = importlib.util.spec_from_file_location("pipecat_bot_example", path / "bot.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(path))


class EnergyVAD(VADAnalyzer):
    """Silero does not fire on synthetic square waves; loudness is enough for the contract run."""

    def __init__(self) -> None:
        super().__init__(sample_rate=16000)

    def num_frames_required(self) -> int:
        return 320

    def voice_confidence(self, buffer: bytes) -> float:
        samples = array.array("h", buffer)
        return 1.0 if samples and max(abs(s) for s in samples) > 2000 else 0.0


class ScriptedSTT(SegmentedSTTService):
    def __init__(self) -> None:
        super().__init__(sample_rate=16000)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        yield TranscriptionFrame("I will pay on Friday", "caller", "2026-10-27T00:00:00Z")


class ScriptedLLM(LLMService):
    """Answers every context with one sentence and a ``record_promise_to_pay`` result."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return
        await self.push_frame(LLMFullResponseStartFrame())
        await self.push_frame(LLMTextFrame("Thank you, "))
        await self.push_frame(LLMTextFrame("noted for Friday."))
        await self.push_frame(
            FunctionCallResultFrame(
                function_name="record_promise_to_pay",
                tool_call_id="t1",
                arguments={"date": "Friday"},
                result={"status": "recorded"},
            )
        )
        await self.push_frame(LLMFullResponseEndFrame())


class ScriptedTTS(TTSService):
    def __init__(self) -> None:
        super().__init__(sample_rate=16000)

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        for _ in range(3):
            yield TTSAudioRawFrame(TONE, 16000, 1, context_id=context_id)


@contextlib.asynccontextmanager
async def pipecat_bot() -> AsyncIterator[str]:
    bot = load_bot()

    def services(_: PareekshaFrameSerializer) -> tuple[Any, Any, Any]:
        return ScriptedSTT(), ScriptedLLM(), ScriptedTTS()

    config = uvicorn.Config(
        bot.create_app(services, EnergyVAD),
        host="127.0.0.1",
        port=0,
        log_level="warning",
        lifespan="off",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}/ws"
    finally:
        server.should_exit = True
        await task


@contextlib.asynccontextmanager
async def audio_v1_agent() -> AsyncIterator[str]:
    async with running_agent(FakeSpeech(["I will pay on Friday"])) as hostport:
        yield f"ws://{hostport}/call"


Case = tuple[Callable[[], Any], Adapter, str]
CASES = [
    pytest.param(audio_v1_agent, AudioV1Adapter(), "audio_v1", id="audio_v1-mock-agent"),
    pytest.param(pipecat_bot, PipecatAdapter(), "pipecat", id="pipecat-example-bot"),
]


async def talk(session: AudioSession, seconds: float = 12.0) -> list[AgentEvent]:
    """Answer the agent: wait for its greeting, speak, listen for the reply, then hang up."""
    events: list[AgentEvent] = []
    spoke = False
    sending = True

    async def send_audio() -> None:
        # Speech needs to follow the agent's greeting; 20 ms real-time pacing like the simulator.
        nonlocal spoke
        while sending:
            speaking = any(isinstance(e, AgentTranscript) and e.role == "agent" for e in events)
            if speaking and not spoke:
                for _ in range(40):
                    await session.send_pcm16(LOUD)
                    await asyncio.sleep(0.02)
                spoke = True
            await session.send_pcm16(QUIET)
            await asyncio.sleep(0.02)

    sender = asyncio.create_task(send_audio())

    async def listen() -> None:
        async for event in session.receive():
            events.append(event)

    try:
        await asyncio.wait_for(listen(), timeout=seconds)
    except TimeoutError:
        pass
    finally:
        sending = False
        await sender
    return events


@pytest.mark.parametrize(("agent_factory", "adapter", "name"), CASES)
async def test_adapter_contract(
    agent_factory: Callable[[], Any], adapter: Adapter, name: AdapterName
) -> None:
    async with agent_factory() as url:
        target = AgentTarget(
            agent_id=uuid.uuid4(),
            adapter=name,
            endpoint_url=url,
            glass_box=True,
        )
        ctx = CallContext(call_id=uuid.uuid4(), language_hint="en-IN")
        session = await adapter.connect(target, ctx)
        async with session:
            events = await talk(session)
    audio = [e for e in events if isinstance(e, AgentAudio)]
    transcripts = [e for e in events if isinstance(e, AgentTranscript)]
    assert audio, f"{name}: no agent audio"
    assert all(len(a.pcm16) == AUDIO_FRAME_BYTES for a in audio), "agent audio is 20 ms frames"
    assert any(t.role == "agent" for t in transcripts), f"{name}: no agent transcript"
    assert any(t.role == "user" and "Friday" in t.text for t in transcripts), "heard the caller"
    if name == "pipecat":
        tools = [e for e in events if isinstance(e, AgentToolCall)]
        assert tools and tools[0].name == "record_promise_to_pay"
        assert tools[0].arguments == {"date": "Friday"}
