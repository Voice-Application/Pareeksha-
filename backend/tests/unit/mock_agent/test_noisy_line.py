"""The mock agent on noisy shipped lines: real ``LineSimulator`` noise, real speech, real socket.

Line noise at 5 and 10 dB sits around the VAD's fixed threshold. It must neither count as the caller
talking (which used to cut the opening and leave the agent silent) nor hide the caller who is.
"""

import contextlib
import functools
from pathlib import Path

import pytest
from mock_agent.bugs import Bug
from mock_agent.speech import wav_to_pcm
from mock_agent.vad import UtteranceDetector
from websockets.asyncio.client import connect

from pareeksha.adapters.base import AUDIO_FRAME_BYTES
from pareeksha.audio.line_simulator import LineSimulator
from pareeksha.audio.profiles import get_profile
from tests.integration.mock_agent_harness import (
    TONE,
    FakeSpeech,
    Recorder,
    running_agent,
    start_message,
    start_reader,
    wait_for,
)

NOISY_LINES = ["pstn_street_10db", "pstn_market_5db", "mobile_bus_5db"]
SPEECH = wav_to_pcm(
    (Path(__file__).parents[2] / "fixtures" / "agent_greeting_5s.wav").read_bytes()
)[: 3 * 32000]
NOISE_S, SPEECH_S, TAIL_S = 2, 3, 2
SPEECH_START, SPEECH_END = NOISE_S * 50, (NOISE_S + SPEECH_S) * 50


@functools.cache
def call_audio(profile: str) -> tuple[bytes, ...]:
    """20 ms frames as the agent receives them: line noise, the caller's 3 s, line noise."""
    line = LineSimulator(get_profile(profile), seed=1)
    track = bytes(NOISE_S * 32000) + SPEECH + bytes(TAIL_S * 32000)
    out = bytearray()
    for i in range(0, len(track), AUDIO_FRAME_BYTES):
        out += line.process_pcm16(track[i : i + AUDIO_FRAME_BYTES])
    return tuple(
        bytes(out[i : i + AUDIO_FRAME_BYTES])
        for i in range(0, len(out) - AUDIO_FRAME_BYTES + 1, AUDIO_FRAME_BYTES)
    )


@pytest.mark.parametrize("profile", NOISY_LINES)
def test_line_noise_alone_is_not_an_utterance(profile: str) -> None:
    vad = UtteranceDetector()
    assert not any(vad.feed(f) for f in call_audio(profile)[:SPEECH_START])
    assert not vad.speaking


@pytest.mark.parametrize("profile", NOISY_LINES)
def test_speech_in_line_noise_is_an_utterance(profile: str) -> None:
    vad = UtteranceDetector()
    utterances = [u for u in map(vad.feed, call_audio(profile)) if u is not None]
    assert sum(len(u) for u in utterances) >= 2 * 32000  # most of the caller's 3 s


class _Speech(FakeSpeech):
    """The agent talks for ``frames`` x 20 ms."""

    def __init__(self, heard: list[str], frames: int) -> None:
        super().__init__(heard)
        self.frames = frames

    async def say(self, text: str, language: str) -> bytes:
        self.said.append((text, language))
        return TONE * self.frames


async def test_line_noise_does_not_cut_the_opening() -> None:
    frames = call_audio("pstn_market_5db")[:SPEECH_START]
    speech = _Speech([], frames=50)
    async with running_agent(speech) as addr, connect(f"ws://{addr}/call") as ws:
        rec = Recorder()
        start_reader(ws, rec)
        await ws.send(start_message("en-IN"))
        for frame in frames:
            await ws.send(frame)
        await wait_for(lambda: rec.audio_frames == 50)
    assert not [m for m in rec.of("transcript") if m["role"] == "user"]


async def test_agent_answers_the_caller_on_a_noisy_line() -> None:
    speech = _Speech(["yes speaking"], frames=5)
    async with running_agent(speech) as addr, connect(f"ws://{addr}/call") as ws:
        rec = Recorder()
        start_reader(ws, rec)
        await ws.send(start_message("en-IN"))
        await wait_for(lambda: rec.audio_frames == 5)
        for frame in call_audio("pstn_market_5db"):
            await ws.send(frame)
        await wait_for(lambda: len(speech.said) >= 2)
    assert next(m["text"] for m in rec.of("transcript") if m["role"] == "user") == "yes speaking"


async def _talk_over_the_opening(bugs: frozenset[Bug]) -> tuple[Recorder, _Speech]:
    """The agent has 3 s to say; the caller talks over it on a 5 dB line, then stops."""
    frames = call_audio("pstn_market_5db")
    speech = _Speech(["hold on"], frames=150)
    async with running_agent(speech, bugs) as addr, connect(f"ws://{addr}/call") as ws:
        rec = Recorder()
        start_reader(ws, rec)
        await ws.send(start_message("en-IN"))
        await wait_for(lambda: rec.audio_frames > 0)
        for frame in frames[:SPEECH_END]:
            await ws.send(frame)
        with contextlib.suppress(TimeoutError):
            await wait_for(lambda: rec.audio_frames == 150)  # 3 s unless the agent was cut off
        return rec, speech


async def test_speech_on_a_noisy_line_still_barges_in() -> None:
    rec, _ = await _talk_over_the_opening(frozenset())
    assert rec.audio_frames < 100


async def test_planted_ignore_interrupt_still_ignores_it_on_a_noisy_line() -> None:
    rec, speech = await _talk_over_the_opening(frozenset({Bug.IGNORE_INTERRUPT}))
    assert rec.audio_frames == 150
    assert speech.heard == ["hold on"]  # never transcribed
