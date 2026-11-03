"""EVAL-07: rubric-2026-10-v2 (parsing from the seed YAML, the pass gate, the judge_v2 prompt)."""

from __future__ import annotations

import pytest
import yaml

from pareeksha.evaluation import rubric
from pareeksha.evaluation.scoring import finalize_scores, gate_reasons
from pareeksha.evaluation.types import CheckResult
from pareeksha.llm.prompts import PROMPTS_DIR, prompt_hash
from pareeksha.schemas.evaluation import JudgeOutput
from tests.unit.evaluation.fakes import judge_json

V1, V2 = rubric.RUBRICS[rubric.RUBRIC_V1], rubric.RUBRICS[rubric.RUBRIC_V2]
KEYS = rubric.DIMENSION_KEYS


def judged(scores: tuple[int, ...] = (4,) * 7, **kw: object) -> JudgeOutput:
    return JudgeOutput.model_validate_json(judge_json(scores, **kw))  # type: ignore[arg-type]


def test_v2_and_v1_are_kept() -> None:
    assert rubric.RUBRICS[rubric.RUBRIC_V2].prompt == "judge_v2"
    assert (
        V1.prompt == "judge_v1" and V1.gate_max_failing_score is None and not V1.gate_failure_types
    )
    assert (
        V1.anchors.startswith("Scale for every dimension")
        and "task_completion (weight 25)" in V1.anchors
    )
    assert prompt_hash("judge_v1") != prompt_hash("judge_v2")


def test_v2_yaml_parsed() -> None:
    spec = yaml.safe_load((rubric._DATA / "rubric-2026-10-v2.yaml").read_text(encoding="utf-8"))
    assert [d["key"] for d in spec["dimensions"]] == list(KEYS)
    assert {d["key"]: d["weight"] for d in spec["dimensions"]} == rubric.WEIGHTS
    assert V2.pass_threshold == 80.0
    assert V2.gate_max_failing_score == 1
    assert V2.gate_failure_types == {"intent_miss", "loop"}
    for d in spec["dimensions"]:  # every anchor reaches the prompt
        for text in d["anchors"].values():
            assert text in V2.anchors
    assert "every caller question or request answered" in V2.anchors
    assert "transferred after the caller explicitly declined a human" in V2.anchors


def test_gate_passes_a_clean_call() -> None:
    out = finalize_scores(judged(), [], rubric=V2)
    assert out.passed and out.review_reasons == [] and not out.needs_human_review


@pytest.mark.parametrize("dim", KEYS)
def test_gate_fails_any_dimension_at_or_below_1(dim: str) -> None:
    scores = tuple(1 if k == dim else 4 for k in KEYS)
    out = finalize_scores(judged(scores), [], rubric=V2)
    assert out.overall_score >= 80 or dim in {"task_completion", "policy_compliance"}
    assert not out.passed
    assert f"gate:{dim}<=1" in out.review_reasons
    assert not out.needs_human_review  # the gate explains the fail; it does not queue the call


def test_gate_fails_on_judge_intent_miss_even_with_score_100() -> None:
    out = finalize_scores(judged(failure_types=["intent_miss"]), [], rubric=V2)
    assert out.overall_score == 100 and not out.passed
    assert out.review_reasons == ["gate:intent_miss"]


def test_gate_fails_on_loop_from_a_check() -> None:
    check = CheckResult("no_loop", "no_loop", passed=False, must_pass=False)
    out = finalize_scores(judged(), [check], failure_types=["loop"], rubric=V2)
    assert not out.passed and "gate:loop" in out.review_reasons


def test_v1_has_no_gate() -> None:
    scores = (4, 4, 4, 4, 1, 4, 4)  # 92.5, conversation_flow 1
    assert finalize_scores(judged(scores, failure_types=["intent_miss"]), [], rubric=V1).passed
    assert not finalize_scores(judged(scores, failure_types=["intent_miss"]), [], rubric=V2).passed


def test_gate_and_existing_rules_combine() -> None:
    must = CheckResult("amount_confirmed", "emi_amount", passed=False, must_pass=True)
    out = finalize_scores(judged((4, 4, 4, 4, 2, 2, 4)), [must], rubric=V2)
    assert not out.passed and out.review_reasons == ["check_failed:amount_confirmed"]
    crit = finalize_scores(judged((4, 4, 4, 4, 0, 4, 4), critical=True), [], rubric=V2)
    assert crit.critical_failure and not crit.passed
    assert crit.review_reasons == ["critical_failure", "gate:conversation_flow<=1"]


def test_gate_reasons_deduplicate_failure_types() -> None:
    assert gate_reasons(dict.fromkeys(KEYS, 4), ["loop", "loop", "latency"], V2) == ["gate:loop"]


def test_judge_v2_prompt_has_responsiveness_and_critical_rules() -> None:
    text = (PROMPTS_DIR / "judge_v2.j2").read_text(encoding="utf-8")
    assert "## Responsiveness" in text
    assert "Facts on file" in text
    assert "stopped responding" in text and "three or more times" in text
    assert "every caller question or request answered" in V2.anchors
