"""FR-MK-2: the mock agent sends glass-box transcript, tool_call and call_end messages."""

import asyncio

from websockets.asyncio.client import connect

from tests.integration.mock_agent_harness import (
    FakeSpeech,
    Recorder,
    read_into,
    running_agent,
    speak,
    start_message,
    start_reader,
    wait_for,
)


async def test_full_call_emits_glass_box_messages() -> None:
    speech = FakeSpeech(["yes speaking", "I will pay friday", "yes correct"])
    async with running_agent(speech) as addr, connect(f"ws://{addr}/call") as ws:
        rec = Recorder()
        reader = asyncio.create_task(read_into(ws, rec))
        await ws.send(start_message("en-IN"))
        for turn in range(3):
            await wait_for(lambda t=turn: len(rec.of("transcript")) >= 2 * t + 1)
            await asyncio.sleep(0.35)  # let the 200 ms agent turn finish
            await speak(ws)
        await wait_for(lambda: bool(rec.of("call_end")))
        await reader

    roles = [(m["role"], m["text"]) for m in rec.of("transcript")]
    assert roles[0][0] == "agent" and "recorded" in roles[0][1]
    assert [r for r, _ in roles].count("user") == 3
    assert all(isinstance(m["t_ms"], int) for m in rec.of("transcript"))
    tool = rec.of("tool_call")
    assert tool[0]["name"] == "record_promise_to_pay"
    assert tool[0]["arguments"]["amount_inr"] == 4500 and tool[0]["result"] == {
        "status": "recorded"
    }
    assert rec.of("call_end")[0]["reason"] == "completed"
    assert rec.audio_frames > 0
    assert any("confirm" in t for t, _ in speech.said)


async def test_per_call_metadata_overrides_bugs() -> None:
    speech = FakeSpeech([])
    async with running_agent(speech) as addr, connect(f"ws://{addr}/call") as ws:
        rec = Recorder()
        start_reader(ws, rec)
        await ws.send(start_message("en-IN", mock_bugs=["no_disclosure"]))
        await wait_for(lambda: bool(rec.of("transcript")))
    assert "recorded" not in rec.of("transcript")[0]["text"]


async def test_stop_message_ends_session_cleanly() -> None:
    speech = FakeSpeech([])
    async with running_agent(speech) as addr, connect(f"ws://{addr}/call") as ws:
        await ws.send(start_message())
        await ws.send('{"type":"stop","reason":"caller_hangup"}')
        await asyncio.wait_for(ws.wait_closed(), 5)
