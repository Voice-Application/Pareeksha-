"""Evaluate one call: masked snapshot, metrics, checks, judge, scoring in code.

Pure with respect to storage: persistence and Kafka I/O are in ``handlers.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pareeksha.evaluation.checks import run_checks
from pareeksha.evaluation.judge import AgentInfo, JudgeInput, mask_turn, run_judge
from pareeksha.evaluation.metrics import CallMetrics, compute_metrics
from pareeksha.evaluation.rubric import RUBRIC_VERSION
from pareeksha.evaluation.scoring import finalize_scores
from pareeksha.evaluation.types import CheckResult, ToolCall, Turn
from pareeksha.llm.client import JSONGenerationError, LLMClient
from pareeksha.llm.prompts import prompt_hash
from pareeksha.schemas.evaluation import JudgeOutput
from pareeksha.schemas.personas import PersonaCreate
from pareeksha.schemas.scenarios import ScenarioCreate

#: Deterministic check type -> failure tag, merged into the judge's ``failure_types``.
CHECK_FAILURE_TYPES = {
    "disclosure_present": "missing_disclosure",
    "forbidden_absent": "policy_violation",
    "language_match": "language_mismatch",
    "no_loop": "loop",
    "amount_confirmed": "wrong_fact",
    "tool_calls_expected": "tool_selection",
}


@dataclass(frozen=True)
class CallSnapshot:
    """What the evaluator needs about a finished call (``calls.metadata`` is never included)."""

    call_id: uuid.UUID
    agent: AgentInfo
    turns: Sequence[Turn]
    language: str = "unknown"
    scenario: ScenarioCreate | None = None
    persona: PersonaCreate | None = None
    tool_calls: Sequence[ToolCall] | None = None
    expected_language: str | None = None
    allowed_languages: Sequence[str] = ()
    expected_tool_calls: Sequence[Mapping[str, Any]] | None = None
    expected_amounts: Mapping[str, Any] | None = None
    agent_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None
    run_item_id: uuid.UUID | None = None
    ws_open_ms: int = 0


@dataclass
class EvaluationRecord:
    """One ``evaluations`` row plus its ``deterministic_checks`` and metrics."""

    id: uuid.UUID
    call_id: uuid.UUID
    rubric_version: str
    status: str  # "ok" | "judge_error"
    judge_model: str
    temperature: float
    prompt_hash: str
    dimensions: dict[str, dict[str, Any]]
    overall_score: float | None
    passed: bool | None
    critical_failure: bool
    needs_human_review: bool
    review_reasons: list[str]
    failure_types: list[str]
    summary: str
    confidence: str | None
    raw_response: dict[str, Any] | None
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int | None
    est_cost: float | None
    checks: list[CheckResult] = field(default_factory=list)
    metrics: CallMetrics = field(default_factory=CallMetrics)


def evaluation_id(call_id: uuid.UUID, rubric_version: str = RUBRIC_VERSION) -> uuid.UUID:
    """Deterministic id: re-evaluating the same call under the same rubric hits the same row."""
    return uuid.uuid5(call_id, f"evaluation:{rubric_version}")


def merge_failure_types(judge: Sequence[str], checks: Sequence[CheckResult]) -> list[str]:
    out = list(dict.fromkeys(judge))
    for c in checks:
        tag = CHECK_FAILURE_TYPES.get(c.check_type)
        if c.passed is False and tag and tag not in out:
            out.append(tag)
    return out


def judge_error_record(
    snap: CallSnapshot,
    model: str,
    checks: list[CheckResult],
    metrics: CallMetrics,
    error: str,
) -> EvaluationRecord:
    """A judge that never produced valid output: no score, always routed to a human."""
    return EvaluationRecord(
        id=evaluation_id(snap.call_id),
        call_id=snap.call_id,
        rubric_version=RUBRIC_VERSION,
        status="judge_error",
        judge_model=model,
        temperature=0.0,
        prompt_hash="sha256:" + prompt_hash("judge_v1"),
        dimensions={},
        overall_score=None,
        passed=None,
        critical_failure=False,
        needs_human_review=True,
        review_reasons=["judge_error"],
        failure_types=merge_failure_types([], checks),
        summary=error[:400],
        confidence=None,
        raw_response=None,
        input_tokens=None,
        output_tokens=None,
        latency_ms=None,
        est_cost=None,
        checks=checks,
        metrics=metrics,
    )


async def evaluate_call(snap: CallSnapshot, client: LLMClient) -> EvaluationRecord:
    """Run the full evaluation pipeline for one call.

    Retryable provider errors (timeouts, 429, 5xx) and permanent ones (bad key) propagate so the
    consumer framework can retry or dead-letter; only "the model kept returning invalid output" is
    stored as ``judge_error``.
    """
    turns = [mask_turn(t) for t in snap.turns]
    metrics = compute_metrics(turns, snap.ws_open_ms)
    checks = run_checks(
        turns,
        disclosures=snap.agent.mandatory_disclosures,
        forbidden=snap.agent.forbidden_phrases,
        expected_language=snap.expected_language,
        allowed_languages=snap.allowed_languages,
        expected_tool_calls=snap.expected_tool_calls,
        tool_calls=snap.tool_calls,
        expected_amounts=snap.expected_amounts,
    )
    data = JudgeInput(
        agent=snap.agent,
        turns=turns,
        metrics=metrics,
        checks=checks,
        call_language=snap.language,
        scenario=snap.scenario,
        persona=snap.persona,
        tool_calls=snap.tool_calls or (),
    )
    model = client.settings.judge_model
    try:
        result = await run_judge(client, data)
    except JSONGenerationError as exc:
        return judge_error_record(snap, model, checks, metrics, f"judge_error: {exc}")

    judge: JudgeOutput = result.parsed
    outcome = finalize_scores(judge, checks)
    return EvaluationRecord(
        id=evaluation_id(snap.call_id),
        call_id=snap.call_id,
        rubric_version=RUBRIC_VERSION,
        status="ok",
        judge_model=result.model,
        temperature=0.0,
        prompt_hash="sha256:" + (result.prompt_hash or prompt_hash("judge_v1")),
        dimensions={k: v.model_dump() for k, v in judge.dimensions},
        overall_score=outcome.overall_score,
        passed=outcome.passed,
        critical_failure=outcome.critical_failure,
        needs_human_review=outcome.needs_human_review,
        review_reasons=outcome.review_reasons,
        failure_types=merge_failure_types(judge.failure_types, checks),
        summary=judge.summary,
        confidence=judge.confidence,
        raw_response=judge.model_dump(mode="json"),
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        latency_ms=result.latency_ms,
        est_cost=result.est_cost,
        checks=checks,
        metrics=metrics,
    )
