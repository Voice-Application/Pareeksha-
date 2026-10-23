"""Calls, evaluations, reviews, promotion, audits (docs/06-api-spec.md section 4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from pareeksha.schemas.common import CallSource, RequestModel

CallStatus = Literal["in_progress", "transcribing", "completed", "error"]
EndReason = Literal[
    "goal_achieved",
    "gave_up",
    "agent_hangup",
    "max_turns",
    "timeout",
    "agent_silent",
    "connect_failed",
    "cancelled",
    "infra_error",
    "upload",
    "import",
]
Speaker = Literal["caller", "agent"]
AudioTrack = Literal["mixed", "caller", "agent", "original"]
CheckType = Literal[
    "disclosure_present",
    "forbidden_absent",
    "language_match",
    "tool_calls_expected",
    "no_loop",
    "amount_confirmed",
]
FailureType = Literal[
    "intent_miss",
    "asr_misrecognition",
    "wrong_fact",
    "tool_selection",
    "tool_arguments",
    "missing_disclosure",
    "policy_violation",
    "language_mismatch",
    "latency",
    "interruption_handling",
    "loop",
    "escalation_error",
    "hallucination",
    "prompt_injection",
]
RegressionTestStatus = Literal["blocking", "scheduled", "manual", "retired"]


class Recordings(BaseModel):
    """Download URLs (``GET /calls/{id}/audio/{track}``); a track is null when not recorded."""

    mixed: str | None = None
    caller: str | None = None
    agent: str | None = None
    original: str | None = None


class TurnOut(BaseModel):
    idx: int
    speaker: Speaker
    text: str
    start_ms: int
    end_ms: int
    ground_truth_text: str | None = Field(default=None, description="simulated caller turns")
    agent_heard_text: str | None = Field(default=None, description="glass-box agents only")
    language_detected: str | None = None
    stt_confidence: float | None = None
    is_barge_in: bool = False


class ToolCallOut(BaseModel):
    seq: int
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    at_ms: int
    turn_idx: int | None = None


class CallMetricsOut(BaseModel):
    first_greeting_ms: int | None = None
    response_latency_p50_ms: int | None = None
    response_latency_p90_ms: int | None = None
    response_latency_p95_ms: int | None = None
    response_latency_max_ms: int | None = None
    barge_in_attempts: int = 0
    barge_in_honoured: int = 0
    agent_stop_time_p50_ms: int | None = None
    silence_gaps_over_2s: int = 0
    turn_count: int = 0
    agent_talk_ratio: float | None = None
    repeated_utterances: int = 0
    caller_asr_wer: float | None = None
    latency_is_approximate: bool = False


class CheckOut(BaseModel):
    check_type: CheckType
    check_key: str
    must_pass: bool = True
    passed: bool | None = Field(default=None, description="null = not applicable")
    evidence_turns: list[int] = Field(default_factory=list)
    detail: str = ""


class DimensionScore(BaseModel):
    """One rubric dimension (docs/08). Keys are rubric dimension keys, e.g. ``task_completion``."""

    score: int = Field(ge=0, le=4)
    evidence_turns: list[int] = Field(default_factory=list)
    reason: str = ""


class EvaluationOut(BaseModel):
    id: UUID
    rubric_version: str = Field(examples=["rubric-2026-10-v1"])
    judge_model: str
    prompt_hash: str = Field(examples=["sha256:..."])
    status: Literal["ok", "judge_error"] = "ok"
    overall_score: float | None = Field(default=None, ge=0, le=100)
    passed: bool | None = None
    critical_failure: bool = False
    needs_human_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    failure_types: list[FailureType] = Field(default_factory=list)
    dimensions: dict[str, DimensionScore] = Field(default_factory=dict)
    summary: str = ""
    confidence: Literal["high", "medium", "low"] | None = None


class CallOut(BaseModel):
    id: UUID
    source: CallSource
    status: CallStatus
    agent_id: UUID | None = None
    run_id: UUID | None = Field(default=None, description="simulated calls: the run it belongs to")
    run_item_id: UUID | None = None
    language: str | None = None
    end_reason: EndReason | None = None
    duration_ms: int | None = None
    started_at: datetime | None = None
    recordings: Recordings = Field(default_factory=Recordings)
    turns: list[TurnOut] = Field(default_factory=list)
    tool_calls: list[ToolCallOut] = Field(default_factory=list)
    metrics: CallMetricsOut | None = None
    checks: list[CheckOut] = Field(default_factory=list)
    evaluation: EvaluationOut | None = None
    speaker_map: dict[str, Speaker] | None = Field(default=None, description="uploads only")


class ReevaluateRequest(RequestModel):
    rubric_version: str | None = None


class DimensionReview(RequestModel):
    score: int = Field(ge=0, le=4)


class ReviewCreate(RequestModel):
    reviewer: str = Field(min_length=1, examples=["preetham"])
    passed: bool
    critical_failure: bool = False
    dimensions: dict[str, DimensionReview] = Field(default_factory=dict)
    notes: str = ""


class HumanReviewOut(BaseModel):
    id: UUID
    evaluation_id: UUID
    reviewer: str
    passed: bool
    critical_failure: bool
    overall_score: float | None = None
    dimensions: dict[str, DimensionReview] = Field(default_factory=dict)
    notes: str = ""
    created_at: datetime


class PromoteRequest(RequestModel):
    failure_type: FailureType
    status: RegressionTestStatus = "blocking"
    baseline_score: float = Field(default=80, ge=0, le=100)
    notes: str = ""


class PromoteResult(BaseModel):
    scenario_id: UUID
    regression_test_id: UUID


class CallSummaryOut(BaseModel):
    """One row of ``GET /calls`` (Audits, Overview review queue, Calibration)."""

    id: UUID
    source: CallSource
    status: CallStatus
    agent_id: UUID | None = None
    run_id: UUID | None = None
    language: str | None = None
    duration_ms: int | None = None
    started_at: datetime | None = None
    overall_score: float | None = Field(default=None, ge=0, le=100)
    passed: bool | None = None
    critical_failure: bool | None = None
    needs_human_review: bool | None = None
    review_reasons: list[str] = Field(default_factory=list)
    failure_types: list[str] = Field(default_factory=list)
    human_reviewed: bool = False
