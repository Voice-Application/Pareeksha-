from __future__ import annotations

from typing import Any

import pytest

from pareeksha.evaluation.evidence import evidence_problems
from pareeksha.evaluation.rubric import DIMENSION_KEYS, WEIGHTS
from pareeksha.evaluation.scoring import finalize_scores, overall_score
from pareeksha.evaluation.types import CheckResult
from pareeksha.schemas.evaluation import JudgeOutput


def judge(
    scores: dict[str, int] | None = None,
    *,
    critical: bool = False,
    review: bool = False,
    confidence: str = "high",
    evidence: list[int] | None = None,
) -> JudgeOutput:
    scores = scores or dict.fromkeys(DIMENSION_KEYS, 4)
    dims: dict[str, Any] = {
        k: {"score": s, "evidence_turns": evidence if evidence is not None else [0], "reason": "r"}
        for k, s in scores.items()
    }
    return JudgeOutput.model_validate(
        {
            "dimensions": dims,
            "critical_failure": critical,
            "needs_human_review": review,
            "failure_types": [],
            "summary": "s",
            "confidence": confidence,
        }
    )


def test_weights_sum_and_worked_example_from_rubric() -> None:
    assert sum(WEIGHTS.values()) == 100
    scores = dict(zip(DIMENSION_KEYS, [1, 1, 0, 3, 2, 3, 4], strict=True))
    assert overall_score(scores) == 40.0


@pytest.mark.parametrize(
    ("fill", "expected"), [(4, 100.0), (3, 75.0), (2, 50.0), (1, 25.0), (0, 0.0)]
)
def test_uniform_scores(fill: int, expected: float) -> None:
    assert overall_score(dict.fromkeys(DIMENSION_KEYS, fill)) == expected


def test_pass_boundary_is_inclusive_80() -> None:
    scores = dict.fromkeys(DIMENSION_KEYS, 4)
    scores.update(task_completion=2, policy_compliance=3, conversation_flow=3)  # loses 12.5+5+2.5
    out = finalize_scores(judge(scores), [])
    assert out.overall_score == 80.0 and out.passed
    scores["escalation"] = 3
    just_below = finalize_scores(judge(scores), [])
    assert just_below.overall_score == 78.75 and not just_below.passed


def test_critical_failure_blocks_pass_and_requires_review() -> None:
    out = finalize_scores(judge(critical=True), [])
    assert out.overall_score == 100.0 and not out.passed
    assert out.critical_failure and out.needs_human_review
    assert out.review_reasons == ["critical_failure"]


def test_failed_must_pass_check_blocks_pass_and_requires_review() -> None:
    check = CheckResult("disclosure_present", "recorded", False)
    out = finalize_scores(judge(), [check])
    assert not out.passed and out.needs_human_review and not out.critical_failure
    assert out.review_reasons == ["check_failed:disclosure_present"]


def test_forbidden_check_failure_is_critical() -> None:
    out = finalize_scores(judge(), [CheckResult("forbidden_absent", "threat", False)])
    assert out.critical_failure and out.review_reasons[0] == "critical_failure"


def test_non_must_pass_and_na_checks_are_ignored() -> None:
    checks = [
        CheckResult("no_loop", "k", False, must_pass=False),
        CheckResult("amount_confirmed", "a", None),
        CheckResult("language_match", "l", True),
    ]
    out = finalize_scores(judge(), checks)
    assert out.passed and not out.needs_human_review and out.review_reasons == []


def test_low_confidence_and_judge_flag_force_review() -> None:
    low = finalize_scores(judge(confidence="low"), [])
    assert low.needs_human_review and low.review_reasons == ["judge_low_confidence"] and low.passed
    flagged = finalize_scores(judge(review=True), [])
    assert flagged.needs_human_review and flagged.review_reasons == []


def test_evidence_valid_and_invalid_indices() -> None:
    assert evidence_problems(judge(evidence=[0, 2]), range(5)) is None
    msg = evidence_problems(judge(evidence=[2, 9]), range(5))
    assert msg is not None and "[9]" in msg and "0..4" in msg
    assert "task_completion" in msg and "escalation" in msg


def test_low_score_without_evidence_is_rejected_but_high_score_is_not() -> None:
    assert evidence_problems(judge(evidence=[]), range(3)) is None  # all 4s
    scores = dict.fromkeys(DIMENSION_KEYS, 4)
    scores["factual_accuracy"] = 0
    msg = evidence_problems(judge(scores, evidence=[]), range(3))
    assert msg is not None and "factual_accuracy scored 0 but cites no evidence_turns" in msg
    assert evidence_problems(judge(scores, evidence=[]), []) is not None  # empty transcript


def test_judge_schema_bounds() -> None:
    with pytest.raises(ValueError, match="score"):
        judge(dict.fromkeys(DIMENSION_KEYS, 5))
