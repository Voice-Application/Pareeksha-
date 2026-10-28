"""Recorder, barge-in plan, turn tracker, speech gate and audio helpers (pure, no pipeline)."""

from __future__ import annotations

import io
import wave
from pathlib import Path

import numpy as np
import pytest

from pareeksha.simulation.audio_util import pcm_seconds, wav_to_pcm16
from pareeksha.simulation.barge_in import LEVEL_PROBABILITY, BargeInScheduler
from pareeksha.simulation.models import SimulationSettings
from pareeksha.simulation.recorder import SAMPLE_RATE, AudioRecorder
from pareeksha.simulation.runner import silero_vad
from pareeksha.simulation.turn_tracker import TurnTracker
from pareeksha.simulation.vad import EnergyVADAnalyzer, SpeechGate, frame_rms
from tests.unit.simulation.simfakes import LOUD_FRAME, tone_wav

QUIET_FRAME = bytes(640)


def _read(wav_bytes: bytes) -> tuple[int, int, np.ndarray]:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        return w.getnchannels(), w.getframerate(), data


# ------------------------------------------------------------------------------ recorder


def test_recorder_aligns_tracks_and_writes_three_equal_files() -> None:
    rec = AudioRecorder()
    rec.add_agent(LOUD_FRAME * 5, 100)  # 100..200 ms
    rec.add_caller(LOUD_FRAME * 10, 400)  # 400..600 ms
    out = rec.finalize()
    assert out.duration_ms == 600

    ch_c, rate_c, caller = _read(out.caller_wav)
    ch_a, rate_a, agent = _read(out.agent_wav)
    ch_m, rate_m, mixed = _read(out.mixed_wav)
    assert (ch_c, ch_a, ch_m) == (1, 1, 2)
    assert rate_c == rate_a == rate_m == SAMPLE_RATE
    assert len(caller) == len(agent) == len(mixed) // 2 == 600 * 16
    assert not caller[: 400 * 16].any() and caller[400 * 16 :].all()
    assert not agent[: 100 * 16].any() and agent[100 * 16 : 200 * 16].all()
    assert not agent[200 * 16 :].any()
    assert (mixed[0::2] == caller).all() and (mixed[1::2] == agent).all()  # L caller, R agent


def test_recorder_never_overlaps_within_a_track_and_pads_to_requested_duration() -> None:
    rec = AudioRecorder()
    rec.add_agent(LOUD_FRAME, 0)
    rec.add_agent(LOUD_FRAME, 5)  # arrived 15 ms early: queued right behind the first frame
    assert rec.duration_ms == 40
    out = rec.finalize(duration_ms=1000)
    assert out.duration_ms == 1000
    assert len(_read(out.caller_wav)[2]) == 16000


def test_recorder_saves_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out = AudioRecorder().finalize(duration_ms=100)
    paths = out.save(tmp_path / "call")
    assert sorted(p.name for p in paths.values()) == ["agent.wav", "caller.wav", "mixed.wav"]
    assert all(p.stat().st_size > 44 for p in paths.values())


# ------------------------------------------------------------------------------ barge-in


def test_barge_in_plan_is_seeded_and_inside_the_window() -> None:
    a = BargeInScheduler(3, seed=7)
    b = BargeInScheduler(3, seed=7)
    plans = [a.plan(n) for n in range(40)]
    assert plans == [b.plan(n) for n in range(40)]
    offsets = [p.offset_s for p in plans if p]
    assert offsets and all(0.8 <= o <= 2.5 for o in offsets)
    assert len({round(o, 1) for o in offsets}) > 3  # not a constant
    assert plans != [BargeInScheduler(3, seed=8).plan(n) for n in range(40)]


@pytest.mark.parametrize("level", range(4))
def test_barge_in_rate_follows_the_interruption_level(level: int) -> None:
    sched = BargeInScheduler(level, seed=11)
    rate = sum(sched.plan(n) is not None for n in range(2000)) / 2000
    assert rate == pytest.approx(LEVEL_PROBABILITY[level], abs=0.04)


def test_barge_in_level_zero_never_interrupts_and_bad_arguments_are_rejected() -> None:
    assert all(BargeInScheduler(0, 1).plan(n) is None for n in range(100))
    with pytest.raises(ValueError, match="interruption_level"):
        BargeInScheduler(4, 1)
    with pytest.raises(ValueError, match="min_s"):
        BargeInScheduler(1, 1, min_s=3, max_s=2)


# ------------------------------------------------------------------------------ turn tracker


def test_turn_tracker_orders_turns_and_attaches_glass_box_by_time() -> None:
    t = TurnTracker()
    t.add_agent_turn(start_ms=0, end_ms=2000, text="greeting", confidence=0.8, language="en-IN")
    t.add_caller_turn(start_ms=1200, end_ms=1900, ground_truth="hi there", is_barge_in=True)
    t.add_agent_turn(start_ms=4000, end_ms=6000, text="amount?")
    t.add_caller_turn(start_ms=7000, end_ms=7500, ground_truth="four thousand", kind="reply")
    t.add_agent_said(10, "Hello, recorded call")
    t.add_agent_heard(3000, "hi there")  # arrives after the caller's first turn, before the reply
    t.add_agent_said(4010, "What amount?")
    t.add_agent_heard(8000, "four thousand")
    t.add_tool_call(6100, "record_promise_to_pay", {"amount": 4000}, {"ok": True})
    assert t.glass_box_seen and t.agent_turns == 2 and t.caller_turns == 2

    turns, tools = t.build()
    assert [(x.idx, x.speaker, x.is_barge_in) for x in turns] == [
        (0, "agent", False),
        (1, "caller", True),
        (2, "agent", False),
        (3, "caller", False),
    ]
    assert turns[0].glass_box_text == "Hello, recorded call"
    assert turns[0].stt_confidence == 0.8 and turns[0].language_detected == "en-IN"
    assert turns[1].agent_heard_text == "hi there" and turns[1].ground_truth_text == "hi there"
    assert turns[2].glass_box_text == "What amount?"
    assert turns[3].agent_heard_text == "four thousand"
    assert [(c.seq, c.name, c.turn_idx, c.at_ms) for c in tools] == [
        (0, "record_promise_to_pay", 2, 6100)
    ]


def test_glass_box_text_of_a_reply_cut_off_before_any_audio_is_not_attributed_to_the_next() -> None:
    t = TurnTracker()
    t.add_agent_turn(start_ms=0, end_ms=2000, text="greeting")
    t.add_agent_turn(start_ms=34000, end_ms=39000, text="just to confirm")
    t.add_agent_said(10, "Hello")
    t.add_agent_said(21000, "Overdue by twelve days")  # barged over: never audible
    t.add_agent_said(32000, "Just to confirm, you will pay")
    t.add_agent_turn(start_ms=50000, end_ms=52000, text="bye")
    t.add_agent_said(50100, "Goodbye")
    turns, _ = t.build()
    assert [x.glass_box_text for x in turns] == [
        "Hello",
        "Just to confirm, you will pay",
        "Goodbye",
    ]


def test_turn_tracker_without_glass_box_and_with_repeated_heard_text() -> None:
    t = TurnTracker()
    t.add_caller_turn(start_ms=0, end_ms=500, ground_truth="hello")
    t.add_agent_heard(1000, "hel")
    t.add_agent_heard(1200, "lo")
    t.add_tool_call(10, "early", {}, None)  # before any agent turn: no owner
    turns, tools = t.build()
    assert turns[0].agent_heard_text == "hel lo"
    assert tools[0].turn_idx is None
    assert not TurnTracker().glass_box_seen


# ------------------------------------------------------------------------------ speech gate


async def test_speech_gate_stamps_edges_without_the_vad_hangover() -> None:
    from pipecat.audio.vad.vad_analyzer import VADParams

    gate = SpeechGate(
        EnergyVADAnalyzer(
            params=VADParams(confidence=0.5, start_secs=0.06, stop_secs=0.2, min_volume=0.0)
        )
    )
    edges = []
    t = 0
    for frame in [QUIET_FRAME] * 5 + [LOUD_FRAME] * 20 + [QUIET_FRAME] * 20:
        t += 20
        edges += await gate.feed(frame, t)
    assert [e.kind for e in edges] == ["start", "end"]
    start, end = edges
    assert 100 <= start.t_ms <= 140  # speech began at frame 6 (t = 120 ms)
    assert start.detected_ms > start.t_ms  # confirmed after vad_start_s
    assert end.t_ms == pytest.approx(500, abs=40)  # last voiced frame, not +200 ms hangover
    assert end.detected_ms > end.t_ms
    assert not gate.speaking and gate.flush(900) is None
    await gate.cleanup()


async def test_speech_gate_ignores_clicks_and_flushes_open_speech() -> None:
    from pipecat.audio.vad.vad_analyzer import VADParams

    gate = SpeechGate(
        EnergyVADAnalyzer(
            params=VADParams(confidence=0.5, start_secs=0.1, stop_secs=0.2, min_volume=0.0)
        )
    )
    t = 0
    edges = []
    for frame in [LOUD_FRAME, QUIET_FRAME, QUIET_FRAME] + [LOUD_FRAME] * 10:
        t += 20
        edges += await gate.feed(frame, t)
    assert [e.kind for e in edges] == ["start"]  # the 20 ms click never started speech
    assert gate.speaking
    end = gate.flush(t + 5)
    assert end is not None and end.kind == "end" and not gate.speaking
    await gate.cleanup()


async def test_silero_gate_finds_a_real_synthetic_voice_turn() -> None:
    """Pipecat's Silero model on a Gnani-TTS clip (5 s of speech, then 2 s of silence)."""
    clip = Path(__file__).parents[2] / "fixtures" / "agent_greeting_5s.wav"
    pcm = wav_to_pcm16(clip.read_bytes())
    gate = SpeechGate(silero_vad(SimulationSettings()))
    edges = []
    for i in range(0, len(pcm), 640):
        edges += await gate.feed(pcm[i : i + 640].ljust(640, b"\x00"), (i // 640 + 1) * 20)
    await gate.cleanup()
    assert [e.kind for e in edges] == ["start", "end"]
    start, end = edges
    assert start.t_ms < 600 and 4500 < end.t_ms <= 5200
    assert end.detected_ms >= end.t_ms + 500  # stop_secs hangover is detected, not stamped


def test_frame_rms() -> None:
    assert frame_rms(b"") == 0.0
    assert frame_rms(QUIET_FRAME) == 0.0
    assert frame_rms(LOUD_FRAME) == pytest.approx(4000)


# ------------------------------------------------------------------------------ audio helpers


def test_wav_to_pcm16_resamples_and_downmixes() -> None:
    same = wav_to_pcm16(tone_wav(0.5, 16000))
    assert len(same) == 16000  # 0.5 s of 16-bit mono at 16 kHz
    assert pcm_seconds(same) == pytest.approx(0.5)
    up = wav_to_pcm16(tone_wav(0.5, 24000))
    assert pcm_seconds(up) == pytest.approx(0.5, abs=0.01)

    stereo = io.BytesIO()
    with wave.open(stereo, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.array([[100, -100]] * 160, dtype="<i2").tobytes())
    mono = np.frombuffer(wav_to_pcm16(stereo.getvalue()), dtype="<i2")
    assert len(mono) == 160 and (mono == 100).all()

    eight_bit = io.BytesIO()
    with wave.open(eight_bit, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(16000)
        w.writeframes(bytes(16))
    with pytest.raises(ValueError, match="16-bit"):
        wav_to_pcm16(eight_bit.getvalue())


def test_agent_language_comes_from_what_the_bot_said_not_from_the_stt_language() -> None:
    t = TurnTracker()
    # the STT ran in kn-IN and transliterated the English reply into Kannada script
    t.add_agent_turn(start_ms=0, end_ms=2000, text="ದಿಸ್ ಕಾಲ್ ಈಸ್ ರೆಕಾರ್ಡೆಡ್", language="kn-IN")
    t.add_agent_turn(start_ms=4000, end_ms=6000, text="ಧನ್ಯವಾದ", language="kn-IN")
    t.add_agent_said(10, "This call is being recorded.")
    t.add_agent_said(4010, "ಧನ್ಯವಾದ, ನಿಮ್ಮ ಇಎಂಐ ಬಾಕಿ ಇದೆ")
    turns, _ = t.build()
    assert [x.language_detected for x in turns] == ["en-IN", "kn-IN"]
