"""Scoring in code (docs/08 section 3). The LLM never produces the overall score."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pareeksha.evaluation.rubric import ACTIVE, WEIGHTS, RubricSpec
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


def gate_reasons(
    scores: Mapping[str, int], failure_types: Iterable[str], rubric: RubricSpec
) -> list[str]:
    """Why the rubric's pass gate fails the call (empty = the gate lets it through).

    v2: a dimension at or below ``gate_max_failing_score``, or a gating failure type (from the
    judge or a failed check, e.g. ``no_loop`` -> ``loop``). v1 has no gate.
    """
    out: list[str] = []
    if rubric.gate_max_failing_score is not None:
        out += [
            f"gate:{k}<={rubric.gate_max_failing_score}"
            for k in WEIGHTS
            if scores[k] <= rubric.gate_max_failing_score
        ]
    out += [f"gate:{t}" for t in dict.fromkeys(failure_types) if t in rubric.gate_failure_types]
    return out


def finalize_scores(
    judge: JudgeOutput,
    checks: Iterable[CheckResult],
    failure_types: Iterable[str] = (),
    rubric: RubricSpec = ACTIVE,
) -> ScoreOutcome:
    """Combine judge output and deterministic checks into the stored verdict.

    Critical failures and failed must-pass checks always set ``needs_human_review``
    (safety errs toward humans). The rubric's pass gate (v2) fails a call on its own; its
    ``gate:...`` reasons are listed in ``review_reasons`` so the verdict is explained, but they do
    not by themselves send the call to human review.
    ``failure_types`` are the merged judge + check failure types (the judge's own are always used).
    A check type in the rubric's ``advisory_checks`` (v3: ``amount_confirmed``) is still stored and
    shown to the judge, but its failure does not count as a failed must-pass check.
    """
    checks = list(checks)
    scores = {k: getattr(judge.dimensions, k).score for k in WEIGHTS}
    score = overall_score(scores)
    failed_must = [
        c
        for c in checks
        if c.must_pass and c.passed is False and c.check_type not in rubric.advisory_checks
    ]
    critical = judge.critical_failure or any(
        c.check_type == "forbidden_absent" for c in failed_must
    )
    reasons = (
        (["critical_failure"] if critical else [])
        + [f"check_failed:{c.check_type}" for c in failed_must]
        + (["judge_low_confidence"] if judge.confidence == "low" else [])
    )
    gate = gate_reasons(scores, [*judge.failure_types, *failure_types], rubric)
    return ScoreOutcome(
        overall_score=score,
        critical_failure=critical,
        passed=score >= rubric.pass_threshold and not critical and not failed_must and not gate,
        needs_human_review=bool(reasons) or judge.needs_human_review,
        review_reasons=reasons + gate,
    )
