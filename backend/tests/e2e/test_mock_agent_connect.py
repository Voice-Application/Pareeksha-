"""FR-MK-1: the mock agent answers the connection test (health + start -> first audio)."""

import asyncio
import json
import urllib.request

from websockets.asyncio.client import connect

from tests.integration.mock_agent_harness import (
    FakeSpeech,
    Recorder,
    running_agent,
    start_message,
    start_reader,
    wait_for,
)


async def test_health_and_first_audio_after_start() -> None:
    async with running_agent(FakeSpeech([])) as addr:
        health = await asyncio.to_thread(
            lambda: json.load(urllib.request.urlopen(f"http://{addr}/health"))
        )
        assert health["status"] == "ok" and health["protocol"] == "pareeksha-audio-v1"
        async with connect(f"ws://{addr}/call") as ws:
            rec = Recorder()
            start_reader(ws, rec)
            await ws.send(start_message())
            await wait_for(lambda: rec.audio_frames > 0)


async def test_non_start_first_frame_is_rejected() -> None:
    async with running_agent(FakeSpeech([])) as addr, connect(f"ws://{addr}/call") as ws:
        await ws.send('{"type":"hello"}')
        await asyncio.wait_for(ws.wait_closed(), 5)
        assert ws.close_code == 1002
