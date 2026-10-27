"""The caller pipeline end to end over a real WebSocket, with fake STT / TTS / brain.

Agents are the real mock agent (VOICE-03, fake speech) or small reactive test agents. Timings are
shrunk with ``FAST``; each call takes a few real seconds because audio is paced in real time.
"""

from __future__ import annotations

import asyncio
import io
import json
import wave
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pareeksha.llm.caller import HistoryLine
from pareeksha.simulation.barge_in import BargeInScheduler
from pareeksha.simulation.models import CallSpec, SimulationSettings
from pareeksha.simulation.processors import split_for_tts
from pareeksha.simulation.runner import CallOutcome, CallRunner
from pareeksha.simulation.runtime import BrainCallerSource, CallerLine
from tests.integration.mock_agent_harness import TONE, FakeSpeech, running_agent
from tests.unit.llm.test_client import make as make_llm
from tests.unit.simulation.simfakes import (
    FAST,
    FakeSTT,
    FakeTTS,
    ReactiveAgent,
    ScriptedCaller,
    agent_server,
    echo_agent,
    energy_vad,
    make_spec,
    persona,
    scenario,
)


async def run_call(
    spec: CallSpec,
    caller: ScriptedCaller,
    *,
    stt: FakeSTT | None = None,
    tts: FakeTTS | None = None,
    settings: SimulationSettings = FAST,
    cancel: asyncio.Event | None = None,
) -> CallOutcome:
    runner = CallRunner(
        stt=stt or FakeSTT(),
        tts=tts or FakeTTS(),
        caller=caller,
        settings=settings,
        vad_factory=energy_vad,
    )
    return await asyncio.wait_for(runner.run(spec, cancel=cancel), timeout=60)


def wav_samples(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")


def events(outcome: CallOutcome, type_: str) -> list[dict[str, Any]]:
    return [{"t_ms": e.t_ms, **e.data} for e in outcome.result.events if e.type == type_]


class LongSpeech(FakeSpeech):
    """Mock-agent speech whose lines last one second, so VAD sees real turns."""

    async def say(self, text: str, language: str) -> bytes:
        self.said.append((text, language))
        return TONE * 50


# ------------------------------------------------------------------------------ happy path


async def test_full_call_against_the_mock_agent(tmp_path: Path) -> None:
    speech = LongSpeech(["yes speaking", "i will pay friday", "yes correct"])
    stt = FakeSTT(["hello", "emi due", "please confirm", "goodbye"])
    caller = ScriptedCaller(["yes speaking", "I will pay on Friday", "yes that is right"])
    async with running_agent(speech) as addr:
        outcome = await run_call(make_spec(f"ws://{addr}/call"), caller, stt=stt)
    r = outcome.result

    assert r.end_reason == "agent_hangup" and r.error is None and r.glass_box
    assert [t.speaker for t in r.turns] == ["agent", "caller"] * 3 + ["agent"]
    assert [t.idx for t in r.turns] == list(range(7))
    assert [t.text for t in r.turns if t.speaker == "agent"] == [
        "hello",
        "emi due",
        "please confirm",
        "goodbye",
    ]
    callers = [t for t in r.turns if t.speaker == "caller"]
    assert [t.ground_truth_text for t in callers] == [
        "yes speaking",
        "I will pay on Friday",
        "yes that is right",
    ]
    # glass box: the agent's own STT heard the caller, and its own line is attached to its turn
    assert [t.agent_heard_text for t in callers] == [
        "yes speaking",
        "i will pay friday",
        "yes correct",
    ]
    assert "recorded" in (r.turns[0].glass_box_text or "")
    assert [c.name for c in r.tool_calls] == ["record_promise_to_pay"]
    assert r.tool_calls[0].turn_idx == 6 and r.tool_calls[0].arguments["amount_inr"] == 4500
    assert all(t.start_ms < t.end_ms for t in r.turns)
    assert all(a.end_ms <= b.start_ms + 50 for a, b in zip(r.turns, r.turns[1:], strict=False))

    # FR-RN-7: three files, same duration to the sample
    assert outcome.recordings is not None
    saved = outcome.save(tmp_path)
    assert saved.recordings is not None
    caller_wav, agent_wav = (
        wav_samples((tmp_path / f"{n}.wav").read_bytes()) for n in ("caller", "agent")
    )
    with wave.open(str(tmp_path / "mixed.wav")) as mixed:
        assert (mixed.getnchannels(), mixed.getframerate()) == (2, 16000)
        assert mixed.getnframes() == len(caller_wav) == len(agent_wav)
    assert abs(len(caller_wav) * 1000 / 16000 - r.duration_ms) < 100
    assert np.abs(caller_wav).max() >= 4000 and np.abs(agent_wav).max() >= 1000
    on_disk = json.loads((tmp_path / "transcript.json").read_text())
    assert on_disk["end_reason"] == "agent_hangup" and len(on_disk["turns"]) == 7

    # per-call usage is collected for the credit log
    kinds = [u.kind for u in r.usage]
    assert kinds.count("stt") == 4 and kinds.count("tts") == 3
    assert all(u.provider == "gnani" for u in r.usage)
    assert events(outcome, "pipeline_overhead")[0]["p95_ms"] < 50


async def test_the_brain_sees_the_dialogue_so_far_and_the_persona_voice_is_used() -> None:
    agent = ReactiveAgent([0.6, 0.6, 0.6], hangup=True)
    caller = ScriptedCaller(["first", "second"])
    tts = FakeTTS()
    stt = FakeSTT(["greeting heard", "reply heard", "closing heard"])
    async with agent_server(agent) as url:
        spec = make_spec(url, persona_over={"voice_id": "Prakash", "speed": 1.25})
        outcome = await run_call(spec, caller, stt=stt, tts=tts)
    assert outcome.result.end_reason == "agent_hangup"
    assert caller.histories[0] == [HistoryLine("agent", "greeting heard")]
    assert caller.histories[1] == [
        HistoryLine("agent", "greeting heard"),
        HistoryLine("caller", "first"),
        HistoryLine("agent", "reply heard"),
    ]
    assert caller.turn_numbers == [1, 2]
    assert tts.voices == ["Prakash", "Prakash"] and tts.speeds == [1.25, 1.25]
    assert agent.started[0]["language_hint"] == "en-IN" and agent.started[0]["sample_rate"] == 16000


async def test_start_metadata_is_passed_to_the_agent() -> None:
    agent = ReactiveAgent([0.3], hangup=True)
    async with agent_server(agent) as url:
        spec = make_spec(url, metadata={"mock_bugs": ["false_waiver"]})
        await run_call(spec, ScriptedCaller([]))
    assert agent.started[0]["metadata"] == {"mock_bugs": ["false_waiver"]}


# ------------------------------------------------------------------------------ end conditions


@pytest.mark.parametrize(
    ("patience", "reason"), [(8, "goal_achieved"), (1, "gave_up")], ids=["goal", "patience"]
)
async def test_the_caller_ends_the_call_when_the_brain_says_so(patience: int, reason: str) -> None:
    agent = ReactiveAgent([0.6, 0.6])
    caller = ScriptedCaller([CallerLine("thanks, that is all, bye", end_call=True)])
    async with agent_server(agent) as url:
        spec = make_spec(url, persona_over={"patience_turns": patience})
        outcome = await run_call(spec, caller)
    r = outcome.result
    assert r.end_reason == reason
    assert r.turns[-1].speaker == "caller" and r.turns[-1].text == "thanks, that is all, bye"
    # the goodbye is played in full, then a short tail of line silence, then the call ends
    assert r.duration_ms >= r.turns[-1].end_ms + int(FAST.goodbye_tail_s * 1000) - 60


async def test_max_turns_ends_the_call_after_the_agents_next_answer() -> None:
    agent = ReactiveAgent([0.5] * 6)
    caller = ScriptedCaller(["one", "two", "three"])
    async with agent_server(agent) as url:
        spec = make_spec(url, scenario_over={"max_turns": 2})
        outcome = await run_call(spec, caller)
    r = outcome.result
    assert r.end_reason == "max_turns"
    assert [t.speaker for t in r.turns] == ["agent", "caller", "agent", "caller", "agent"]
    assert len(caller.histories) == 2  # the brain was not asked a third time


async def test_agent_that_never_speaks_gets_hello_then_agent_silent() -> None:
    agent = ReactiveAgent([], speak_first=False)
    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url), ScriptedCaller([]))
    r = outcome.result
    assert r.end_reason == "agent_silent"
    assert [(t.speaker, t.kind, t.text) for t in r.turns] == [("caller", "hello", "Hello?")]
    assert 1500 <= r.duration_ms <= 3500  # first_silence 0.8 s + speech + mid_silence 0.8 s


async def test_mid_call_silence_gets_one_nudge_then_agent_silent() -> None:
    agent = ReactiveAgent([0.6])  # greets, then never answers
    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url), ScriptedCaller(["yes who is this"]))
    r = outcome.result
    assert r.end_reason == "agent_silent"
    kinds = [(t.speaker, t.kind) for t in r.turns]
    assert kinds == [("agent", None), ("caller", "reply"), ("caller", "nudge")]
    assert r.turns[2].text == "Hello, are you still there?"


async def test_nudge_and_hello_are_spoken_in_the_persona_language() -> None:
    agent = ReactiveAgent([], speak_first=False)
    async with agent_server(agent) as url:
        outcome = await run_call(
            make_spec(url, persona_over={"language": "kn-IN"}), ScriptedCaller([])
        )
    assert outcome.result.turns[0].text == "ಹಲೋ?"


async def test_hard_timeout() -> None:
    agent = ReactiveAgent([30.0])
    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url, max_call_seconds=2), ScriptedCaller([]))
    assert outcome.result.end_reason == "timeout"
    assert 1900 <= outcome.result.duration_ms <= 3500


async def test_cancel_ends_the_call_with_a_result() -> None:
    agent = ReactiveAgent([30.0])
    cancel = asyncio.Event()
    async with agent_server(agent) as url:
        asyncio.get_running_loop().call_later(1.0, cancel.set)
        outcome = await run_call(make_spec(url), ScriptedCaller([]), cancel=cancel)
    assert outcome.result.end_reason == "cancelled"
    assert outcome.recordings is not None and outcome.recordings.duration_ms >= 900


async def test_connect_failure_is_reported_not_raised() -> None:
    outcome = await run_call(make_spec("ws://127.0.0.1:1/call"), ScriptedCaller([]))
    assert outcome.result.end_reason == "connect_failed"
    assert outcome.result.error and "cannot connect" in outcome.result.error
    assert outcome.recordings is None and outcome.result.turns == []


async def test_unavailable_adapter_is_an_infra_error() -> None:
    spec = make_spec("ws://127.0.0.1:1/call")
    spec.agent = spec.agent.model_copy(update={"adapter": "vapi"})
    outcome = await run_call(spec, ScriptedCaller([]))
    assert outcome.result.end_reason == "infra_error" and "vapi" in (outcome.result.error or "")


# ------------------------------------------------------------------------------ failures


async def test_brain_failure_is_an_infra_error() -> None:
    agent = ReactiveAgent([0.6, 0.6])
    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url), ScriptedCaller([], fail_after=0))
    assert outcome.result.end_reason == "infra_error"
    assert "caller brain" in (outcome.result.error or "") and "fake llm outage" in (
        outcome.result.error or ""
    )


async def test_tts_failure_is_an_infra_error() -> None:
    agent = ReactiveAgent([0.6, 0.6])
    tts = FakeTTS()
    tts.fail = True
    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url), ScriptedCaller(["hi"]), tts=tts)
    assert outcome.result.end_reason == "infra_error" and "caller TTS" in (
        outcome.result.error or ""
    )


async def test_stt_outage_asks_to_repeat_then_gives_up() -> None:
    agent = ReactiveAgent([0.6] * 6)
    stt = FakeSTT(fail=True)
    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url), ScriptedCaller([]), stt=stt)
    r = outcome.result
    assert r.end_reason == "infra_error" and "could not understand" in (r.error or "")
    repeats = [t for t in r.turns if t.kind == "repeat"]
    assert len(repeats) == FAST.max_unintelligible - 1
    assert repeats[0].text.startswith("Sorry, I could not hear that")
    assert events(outcome, "stt_error")


async def test_one_unreadable_turn_is_recovered_by_asking_again() -> None:
    agent = ReactiveAgent([0.6, 0.6, 0.6], hangup=True)
    stt = FakeSTT(["", "I can hear you now", "bye"])
    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url), ScriptedCaller(["yes please go ahead"]), stt=stt)
    r = outcome.result
    assert r.end_reason == "agent_hangup"
    assert [t.kind for t in r.turns if t.speaker == "caller"] == ["repeat", "reply"]


# ------------------------------------------------------------------------------ barge-in


def seed_with_early_plan(level: int, turn: int = 0) -> int:
    for seed in range(200):
        if BargeInScheduler(level, seed).plan(turn) is not None:
            return seed
    raise AssertionError("no seed plans an interruption")


async def test_barge_in_starts_at_the_planned_time_and_the_agent_stops() -> None:
    seed = seed_with_early_plan(3)
    plan = BargeInScheduler(3, seed).plan(0)
    assert plan is not None
    agent = ReactiveAgent([5.0, 0.6], hangup=True)
    caller = ScriptedCaller(["excuse me, one question", "ok that works"])
    async with agent_server(agent) as url:
        spec = make_spec(url, persona_over={"interruption_level": 3}, seed=seed)
        outcome = await run_call(spec, caller)
    r = outcome.result
    attempt = r.barge_in_attempts[0]
    assert 800 <= attempt.planned_offset_ms <= 2500
    assert attempt.agent_speaking_at_start is True and not attempt.cancelled
    assert attempt.started_ms is not None
    assert abs(attempt.started_ms - attempt.scheduled_ms) < 150  # FR-RN-6: logged and on time
    barge = next(t for t in r.turns if t.is_barge_in)
    assert barge.kind == "barge_in" and barge.speaker == "caller"
    assert agent.stopped_early >= 1
    first_agent = r.turns[0]
    assert first_agent.speaker == "agent" and first_agent.end_ms < 3500  # cut short, not 5 s
    # the cut-off turn was not answered: the caller waited for the agent's reply to the interruption
    assert [t.speaker for t in r.turns] == ["agent", "caller", "agent"]
    assert r.end_reason == "agent_hangup"
    assert events(outcome, "barge_in_planned")


async def test_an_agent_that_ignores_the_interruption_is_answered_after_it_finishes() -> None:
    seed = seed_with_early_plan(3)
    agent = ReactiveAgent([3.5, 0.5], honour=False, hangup=True)
    caller = ScriptedCaller(["hello hello", "fine"])
    async with agent_server(agent) as url:
        spec = make_spec(url, persona_over={"interruption_level": 3}, seed=seed)
        outcome = await run_call(spec, caller)
    r = outcome.result
    assert agent.stopped_early == 0
    assert r.turns[0].speaker == "agent" and r.turns[0].end_ms >= 3300  # talked all the way
    barge = next(t for t in r.turns if t.is_barge_in)
    assert barge.start_ms < r.turns[0].end_ms  # overlapped the agent
    assert r.barge_in_attempts[0].agent_speaking_at_start is True
    # the agent's long turn ended after our interruption, so the caller answered it normally
    assert [t.kind for t in r.turns if t.speaker == "caller"] == ["barge_in", "reply"]


async def test_barge_in_is_dropped_when_the_agent_finishes_first() -> None:
    seed = seed_with_early_plan(3)
    agent = ReactiveAgent([0.5, 0.5], hangup=True)  # shorter than the 0.8 s minimum offset
    async with agent_server(agent) as url:
        spec = make_spec(url, persona_over={"interruption_level": 3}, seed=seed)
        outcome = await run_call(spec, ScriptedCaller(["sure", "ok"]))
    r = outcome.result
    assert r.barge_in_attempts and r.barge_in_attempts[0].cancelled
    assert r.barge_in_attempts[0].started_ms is None
    assert not any(t.is_barge_in for t in r.turns)
    assert next(t.kind for t in r.turns if t.speaker == "caller") == "reply"


async def test_a_brain_failure_during_a_planned_interruption_does_not_fail_the_call() -> None:
    seed = seed_with_early_plan(3)
    agent = ReactiveAgent([2.0, 0.5], hangup=True)
    caller = ScriptedCaller([], fail_after=0)
    async with agent_server(agent) as url:
        spec = make_spec(url, persona_over={"interruption_level": 3}, seed=seed)
        outcome = await run_call(spec, caller)
    # the interruption was skipped; the failure surfaces only when the caller must really answer
    assert events(outcome, "barge_in_skipped")
    assert outcome.result.end_reason == "infra_error"


# ------------------------------------------------------------------------------ chunked TTS

LONG_LINE = "Hello, thank you for calling me back. I wanted to ask you about my EMI amount today."


def test_long_lines_are_cut_after_the_first_sentence_only() -> None:
    assert split_for_tts("Short line.") == ["Short line."]
    assert split_for_tts(LONG_LINE) == [
        "Hello, thank you for calling me back.",
        "I wanted to ask you about my EMI amount today.",
    ]
    one_long = "a" * 80
    assert split_for_tts(one_long) == [one_long]
    assert split_for_tts("एक लंबा वाक्य जो साठ अक्षरों से ज्यादा है। दूसरा वाक्य यहाँ है।") == [
        "एक लंबा वाक्य जो साठ अक्षरों से ज्यादा है।",
        "दूसरा वाक्य यहाँ है।",
    ]


async def test_a_long_line_is_voiced_in_two_parts_and_played_without_a_gap() -> None:
    agent = ReactiveAgent([0.6, 0.6], hangup=True)
    tts = FakeTTS(seconds_per_char=0.01)
    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url), ScriptedCaller([LONG_LINE]), tts=tts)
    assert tts.said == [
        "Hello, thank you for calling me back.",
        "I wanted to ask you about my EMI amount today.",
    ]
    caller_turn = next(t for t in outcome.result.turns if t.speaker == "caller")
    assert caller_turn.text == LONG_LINE
    seconds = sum(len(x) for x in tts.said) * 0.01
    assert (caller_turn.end_ms - caller_turn.start_ms) / 1000 == pytest.approx(seconds, abs=0.15)
    assert [e["characters"] for e in events(outcome, "caller_tts")] == [37, 46]


async def test_the_microphone_waits_in_silence_for_a_late_second_part() -> None:
    agent = ReactiveAgent([0.6, 0.6], hangup=True)
    tts = FakeTTS(seconds_per_char=0.01, delays={"EMI amount": 0.8})
    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url), ScriptedCaller([LONG_LINE]), tts=tts)
    r = outcome.result
    turn = next(t for t in r.turns if t.speaker == "caller")
    # 0.40 s + 0.46 s of speech, and the 0.8 s synthesis of part two overlaps only 0.4 s of it
    assert (turn.end_ms - turn.start_ms) / 1000 >= 0.4 + 0.46 + 0.25
    assert r.end_reason == "agent_hangup" and turn.text == LONG_LINE


async def test_a_failing_second_part_fails_the_call_once() -> None:
    agent = ReactiveAgent([0.6, 0.6])

    class FailsOnRest(FakeTTS):
        async def synthesize(self, text: str, voice: str | None, language: str, **kw: Any) -> Any:
            if "EMI amount" in text:
                self.fail = True
            return await super().synthesize(text, voice, language, **kw)

    async with agent_server(agent) as url:
        outcome = await run_call(make_spec(url), ScriptedCaller([LONG_LINE]), tts=FailsOnRest())
    assert outcome.result.end_reason == "infra_error"


# ------------------------------------------------------------------------------ persona habits


async def test_caller_speaks_first_when_the_scenario_says_so() -> None:
    agent = ReactiveAgent([0.6, 0.6], speak_first=False, hangup=True)
    caller = ScriptedCaller(["hello, is this Suraksha Finance", "yes go ahead"])
    async with agent_server(agent) as url:
        spec = make_spec(url, scenario_over={"caller_speaks_first": True})
        outcome = await run_call(spec, caller)
    r = outcome.result
    assert r.turns[0].speaker == "caller" and r.turns[0].text == "hello, is this Suraksha Finance"
    assert caller.histories[0] == []
    assert r.end_reason == "agent_hangup"


async def test_long_pauses_persona_waits_before_each_reply() -> None:
    agent = ReactiveAgent([0.5, 0.5], hangup=True)
    async with agent_server(agent) as url:
        spec = make_spec(url, persona_over={"silence_habit": "long_pauses"})
        outcome = await run_call(spec, ScriptedCaller(["hmm okay"]))
    pauses = events(outcome, "caller_pause")
    assert pauses and 0.2 <= pauses[0]["seconds"] <= 0.3


async def test_goes_silent_persona_can_stay_quiet_before_replying() -> None:
    agent = ReactiveAgent([0.5, 0.5], hangup=True)
    settings = replace(FAST, goes_silent_probability=1.0, goes_silent_s=0.5, mid_silence_s=3.0)
    async with agent_server(agent) as url:
        spec = make_spec(url, persona_over={"silence_habit": "goes_silent"})
        outcome = await run_call(spec, ScriptedCaller(["sorry, I was away"]), settings=settings)
    pauses = events(outcome, "caller_pause")
    assert pauses and pauses[0]["seconds"] == 0.5


async def test_a_reply_is_dropped_if_the_agent_speaks_again_while_the_caller_hesitates() -> None:
    agent = ReactiveAgent([0.5, 0.5, 0.5], hangup=True, honour=False)
    settings = replace(FAST, long_pause_s=(1.5, 1.5), mid_silence_s=1.0, first_silence_s=5)
    async with agent_server(agent) as url:
        spec = make_spec(url, persona_over={"silence_habit": "long_pauses"})
        outcome = await run_call(spec, ScriptedCaller(["a", "b", "c"]), settings=settings)
    assert outcome.result.end_reason in {"agent_hangup", "agent_silent", "max_turns"}


# ------------------------------------------------------------------------------ line simulation


async def test_line_noise_is_present_even_while_the_caller_is_silent() -> None:
    async def caller_track(profile: str) -> np.ndarray:
        agent = ReactiveAgent([0.6, 0.6], hangup=True)
        async with agent_server(agent) as url:
            out = await run_call(make_spec(url, profile=profile), ScriptedCaller(["yes"]))
        assert out.recordings is not None
        return wav_samples(out.recordings.caller_wav)

    clean = await caller_track("clean_16k")
    noisy = await caller_track("pstn_street_10db")
    before_speech = slice(0, 8000)  # the caller has not said anything in the first 0.5 s
    assert not clean[before_speech].any()
    assert np.sqrt(np.mean(noisy[before_speech].astype(float) ** 2)) > 20


# ------------------------------------------------------------------------------ brain adapter


async def test_brain_caller_source_wraps_caller_brain_and_reports_usage() -> None:
    from pareeksha.llm.caller import CallerBrain

    client, provider, _ = make_llm(
        [
            '{"utterance": "I can pay on Friday", "end_call": false}',
            '{"utterance": "bye", "end_call": true}',
        ]
    )
    source = BrainCallerSource(CallerBrain(client, seed=3))
    first = await source.next_line(persona(), scenario(), [], 1)
    assert first.utterance == "I can pay on Friday" and not first.end_call
    assert first.usage is not None and first.usage.kind == "llm"
    assert first.usage.input_tokens == 100 and first.usage.output_tokens == 10
    last = await source.next_line(
        persona(), scenario(), [HistoryLine("agent", "ok"), HistoryLine("caller", "x")], 2
    )
    assert last.end_call and len(provider.requests) == 2


# ------------------------------------------------------------------------------ NFR-2 loopback


def first_onsets(samples: np.ndarray, min_gap_ms: int = 150, threshold: int = 1500) -> list[float]:
    """Times (ms) at which sound starts after at least ``min_gap_ms`` of quiet."""
    loud = np.abs(samples) > threshold
    idx: list[int] = np.flatnonzero(loud).tolist()
    onsets: list[float] = []
    last = -(10**9)
    for i in idx:
        if i - last > min_gap_ms * 16:
            onsets.append(i / 16)
        last = i
    return onsets


async def test_loopback_overhead_against_an_echo_agent_is_under_50_ms() -> None:
    """NFR-2: at most 50 ms between a caller frame leaving and its echo arriving."""
    caller = ScriptedCaller(["one"])
    async with agent_server(echo_agent) as url:
        # the caller speaks, then nudges twice (mid-call silence): three bursts to compare
        spec = make_spec(url, scenario_over={"caller_speaks_first": True}, max_call_seconds=4)
        outcome = await run_call(spec, caller, settings=replace(FAST, mid_silence_s=0.9))
    assert outcome.recordings is not None
    sent = first_onsets(wav_samples(outcome.recordings.caller_wav))
    echoed = first_onsets(wav_samples(outcome.recordings.agent_wav))
    assert len(sent) >= 3 and len(echoed) >= 3
    lags = [e - s for s, e in zip(sent, echoed, strict=False)]
    assert all(0 <= lag <= 50 for lag in lags), lags
    hop = events(outcome, "pipeline_overhead")[0]
    assert hop["frames"] > 20 and hop["p95_ms"] < 5 and hop["max_ms"] < 50
