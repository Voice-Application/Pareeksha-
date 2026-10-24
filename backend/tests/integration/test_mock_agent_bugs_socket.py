"""Planted bugs 3 and 4 over the socket (bugs 1, 2, 5 are covered in the policy unit tests)."""

import asyncio

from mock_agent.bugs import Bug
from websockets.asyncio.client import connect

from tests.integration.mock_agent_harness import (
    LOUD,
    FakeSpeech,
    Recorder,
    running_agent,
    speak,
    start_message,
    start_reader,
    wait_for,
)


async def test_bug_english_to_kannada_uses_english_tts() -> None:
    speech = FakeSpeech([])
    async with running_agent(speech, frozenset({Bug.ENGLISH_TO_KANNADA})) as addr:
        async with connect(f"ws://{addr}/call") as ws:
            rec = Recorder()
            start_reader(ws, rec)
            await ws.send(start_message("kn-IN"))
            await wait_for(lambda: bool(speech.said))
    assert speech.said[0][1] == "en-IN"


async def _barge_in_call(bugs: frozenset[Bug]) -> tuple[int, FakeSpeech]:
    speech = FakeSpeech(["I will pay friday"])

    async with running_agent(speech, bugs) as addr, connect(f"ws://{addr}/call") as ws:
        rec = Recorder()
        start_reader(ws, rec)
        await ws.send(start_message("en-IN"))
        await wait_for(lambda: rec.audio_frames > 0)
        # Caller talks over the agent's greeting (200 ms turn) for 400 ms, then goes quiet.
        for _ in range(20):
            await ws.send(LOUD)
        await speak(ws, speech_frames=0, silence_frames=45)
        await asyncio.sleep(0.6)
        return len(rec.of("transcript")), speech


async def test_barge_in_is_heard_normally() -> None:
    count, speech = await _barge_in_call(frozenset())
    assert count >= 3  # agent greeting, user (interruption), agent reply
    assert speech.heard == []


async def test_bug_ignore_interrupt_never_hears_interruption() -> None:
    count, speech = await _barge_in_call(frozenset({Bug.IGNORE_INTERRUPT}))
    assert count == 1  # only the greeting; the interruption was never transcribed
    assert speech.heard == ["I will pay friday"]
