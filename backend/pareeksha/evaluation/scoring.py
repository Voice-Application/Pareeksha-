"""Scoring in code (docs/08 section 3). The LLM never produces the overall score."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pareeksha.evaluation.rubric import PASS_THRESHOLD, WEIGHTS
from pareeksha.evaluation.types import CheckResult
from pareeksha.schemas.evaluation import JudgeOutput


def overall_score(scores: Mapping[str, int]) -> float:
    """Weighted 0-100 score from 0-4 dimension scores (every rubric key must be present)."""
    return round(sum(WEIGHTS[k] * scores[k] / 4 for k in WEIGHTS), 2)


@dataclass(frozen=True)
class ScoreOutcome:
    overall_score: float
    critical_failure: bool
    passed: bool
    needs_human_review: bool
    review_reasons: list[str] = field(default_factory=list)


def finalize_scores(judge: JudgeOutput, checks: Iterable[CheckResult]) -> ScoreOutcome:
    """Combine judge output and deterministic checks into the stored verdict.

    Critical failures and failed must-pass checks always set ``needs_human_review``
    (safety errs toward humans).
    """
    score = overall_score({k: getattr(judge.dimensions, k).score for k in WEIGHTS})
    failed_must = [c for c in checks if c.must_pass and c.passed is False]
    critical = judge.critical_failure or any(
        c.check_type == "forbidden_absent" for c in failed_must
    )
    reasons = (
        (["critical_failure"] if critical else [])
        + [f"check_failed:{c.check_type}" for c in failed_must]
        + (["judge_low_confidence"] if judge.confidence == "low" else [])
    )
    return ScoreOutcome(
        overall_score=score,
        critical_failure=critical,
        passed=score >= PASS_THRESHOLD and not critical and not failed_must,
        needs_human_review=bool(reasons) or judge.needs_human_review,
        review_reasons=reasons,
    )
