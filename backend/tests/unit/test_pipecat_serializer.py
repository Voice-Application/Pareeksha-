"""``PareekshaFrameSerializer``, ``GlassBoxProcessor`` and ``PipecatAdapter`` framing."""

from __future__ import annotations

import json

import pytest
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
)

from pareeksha.adapters.base import AUDIO_FRAME_BYTES, AgentAudio, parse_agent_message
from pareeksha.adapters.pipecat_adapter import PipecatSession
from pareeksha.adapters.pipecat_serializer import PareekshaFrameSerializer
from pareeksha.adapters.registry import get_adapter

START = json.dumps(
    {"type": "start", "protocol": "pareeksha-audio-v1", "call_id": "c1", "language_hint": "kn-IN"}
)


async def test_binary_frames_become_input_audio_at_16k() -> None:
    frame = await PareekshaFrameSerializer().deserialize(bytes(640))
    assert isinstance(frame, InputAudioRawFrame)
    assert (frame.sample_rate, frame.num_channels, len(frame.audio)) == (16000, 1, 640)
    assert await PareekshaFrameSerializer().deserialize(b"") is None


async def test_start_is_remembered_and_stop_ends_the_pipeline() -> None:
    ser = PareekshaFrameSerializer()
    assert ser.language == "en-IN"
    assert await ser.deserialize(START) is None
    assert ser.language == "kn-IN" and ser.start_message is not None
    assert ser.start_message.call_id == "c1"
    end = await ser.deserialize(json.dumps({"type": "stop", "reason": "caller_hangup"}))
    assert isinstance(end, EndFrame) and end.reason == "caller_hangup"


@pytest.mark.parametrize("raw", ["not json", "[1]", '{"type":"future"}'])
async def test_unknown_text_frames_are_ignored(raw: str) -> None:
    assert await PareekshaFrameSerializer().deserialize(raw) is None


async def test_output_audio_is_resampled_to_16k_pcm() -> None:
    ser = PareekshaFrameSerializer()
    pcm24k = bytes(2 * 2400)  # 100 ms at 24 kHz
    total = 0
    for _ in range(5):
        out = await ser.serialize(OutputAudioRawFrame(pcm24k, 24000, 1))
        total += len(out or b"")
    assert 2 * 7000 <= total <= 2 * 8000  # 500 ms at 16 kHz, minus the resampler's held tail


async def test_end_and_cancel_announce_call_end() -> None:
    ser = PareekshaFrameSerializer()
    ended = parse_agent_message(str(await ser.serialize(EndFrame())))
    cancelled = parse_agent_message(str(await ser.serialize(CancelFrame())))
    assert (ended.type, cancelled.type) == ("call_end", "call_end")
    assert cancelled.reason == "cancelled"  # type: ignore[union-attr]


async def test_glass_box_messages_pass_through_and_others_are_dropped() -> None:
    ser = PareekshaFrameSerializer()
    msg = {"type": "transcript", "role": "agent", "text": "ನಮಸ್ಕಾರ", "t_ms": 5}
    sent = await ser.serialize(OutputTransportMessageFrame(message=msg))
    assert json.loads(str(sent)) == msg
    assert await ser.serialize(OutputTransportMessageFrame(message={"type": "rtvi"})) is None
    assert await ser.serialize(InterruptionFrame()) is None


async def test_pipecat_session_reframes_audio_into_20ms_frames() -> None:
    session = PipecatSession.__new__(PipecatSession)  # no socket needed for the framing
    first = session._on_binary(bytes(AUDIO_FRAME_BYTES + 100))
    assert [len(e.pcm16) for e in first if isinstance(e, AgentAudio)] == [AUDIO_FRAME_BYTES]
    second = session._on_binary(bytes(AUDIO_FRAME_BYTES * 2 - 100))
    assert len(second) == 2
    assert session._on_binary(b"") == []


def test_registry_ships_the_pipecat_adapter() -> None:
    assert get_adapter("pipecat").name == "pipecat"
