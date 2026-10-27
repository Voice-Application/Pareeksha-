"""EVAL-04b: uncertain role detection routes the call to a human; per-agent speech override."""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import ValidationError

from pareeksha.audit.roles import (
    ROLE_DISAGREEMENT,
    ROLE_LOW_CONFIDENCE,
    role_review_reasons,
)
from pareeksha.evaluation.evaluator import evaluate_call
from pareeksha.schemas.agents import AgentCreate, AgentUpdate
from pareeksha.speech.agent_config import speech_selection
from pareeksha.speech.base import SpeechConfigError, SpeechProviderName
from tests.fixtures import synthetic_calls as sc
from tests.unit.evaluation.fakes import ScriptedProvider, client_for, judge_json


def detection(**fields: object) -> dict[str, object]:
    return {"event": "role_detection", "method": "llm", **fields}


@pytest.mark.parametrize(
    ("event_log", "expected"),
    [
        ([detection(llm_confidence="high", agrees_with_heuristic=True)], []),
        ([detection(llm_confidence="medium", agrees_with_heuristic=True)], []),
        ([detection(llm_confidence="high", agrees_with_heuristic=False)], [ROLE_DISAGREEMENT]),
        ([detection(llm_confidence="low", agrees_with_heuristic=True)], [ROLE_LOW_CONFIDENCE]),
        (
            [{"event": "stt"}, detection(llm_confidence="low", agrees_with_heuristic=False)],
            [ROLE_LOW_CONFIDENCE, ROLE_DISAGREEMENT],
        ),
        # no LLM verdict (not configured / unusable): nothing to compare, so no extra flag
        ([detection(llm_confidence=None, agrees_with_heuristic=None, method="heuristic")], []),
        ([{"event": "stt"}], []),
        ([], []),
        (None, []),
        ("not a list", []),
        (["junk", 3], []),
    ],
)
def test_role_review_reasons(event_log: object, expected: list[str]) -> None:
    assert role_review_reasons(event_log) == expected


async def test_review_reasons_force_human_review_on_a_clean_call() -> None:
    snap = dataclasses.replace(sc.clean_call(), review_reasons=(ROLE_DISAGREEMENT,))
    provider = ScriptedProvider([judge_json((4, 4, 4, 3, 4, 4, 4), evidence=[2])])
    rec = await evaluate_call(snap, client_for(provider))
    assert rec.passed and not rec.critical_failure
    assert rec.needs_human_review and rec.review_reasons == [ROLE_DISAGREEMENT]


async def test_review_reasons_are_kept_when_the_judge_fails() -> None:
    snap = dataclasses.replace(sc.clean_call(), review_reasons=(ROLE_LOW_CONFIDENCE,))
    bad = judge_json(evidence=[99])
    rec = await evaluate_call(snap, client_for(ScriptedProvider([bad, bad, bad])))
    assert rec.status == "judge_error" and rec.needs_human_review
    assert rec.review_reasons == ["judge_error", ROLE_LOW_CONFIDENCE]


# ------------------------------------------------------------------ per-agent speech override


def test_speech_selection_reads_adapter_config() -> None:
    assert speech_selection(None) is None
    assert speech_selection({}) is None
    assert speech_selection({"speech": {}}) is None
    sel = speech_selection({"speech": {"stt": "deepgram", "tts": "gnani"}, "other": 1})
    assert sel is not None
    assert (sel.stt, sel.tts) == (SpeechProviderName.DEEPGRAM, SpeechProviderName.GNANI)
    only_stt = speech_selection({"speech": {"stt": "gnani"}})
    assert only_stt is not None and only_stt.tts is None


@pytest.mark.parametrize("bad", ["gnani", {"stt": "nope"}, {"stt": "gnani", "voice": "x"}])
def test_invalid_speech_override_is_rejected(bad: object) -> None:
    with pytest.raises(SpeechConfigError):
        speech_selection({"speech": bad})


def test_agent_schema_validates_the_override() -> None:
    ok = AgentCreate(
        name="a", endpoint_url="ws://x", adapter_config={"speech": {"stt": "gnani"}, "k": 1}
    )
    assert ok.adapter_config["speech"] == {"stt": "gnani"}
    with pytest.raises(ValidationError, match=r"adapter_config\.speech"):
        AgentCreate(name="a", endpoint_url="ws://x", adapter_config={"speech": {"stt": "nope"}})
    with pytest.raises(ValidationError):
        AgentUpdate(adapter_config={"speech": "gnani"})
    assert AgentUpdate().adapter_config is None
