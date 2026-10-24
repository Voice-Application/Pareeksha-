"""Runs (docs/06-api-spec.md section 3)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from pareeksha.schemas.common import RequestModel

RunKind = Literal["matrix", "regression", "dry_run"]
RunStatus = Literal["draft", "queued", "running", "completed", "partial", "cancelled", "failed"]
RunItemStatus = Literal[
    "queued",
    "connecting",
    "in_progress",
    "completed",
    "evaluating",
    "evaluated",
    "judge_error",
    "error",
    "cancelled",
    "skipped_budget",
]
RegressionStatus = Literal["blocking", "scheduled", "manual", "retired"]


class RunConfig(RequestModel):
    max_concurrency: int = Field(default=3, ge=1, le=20)
    seed: int = 42
    dry_run: bool = False


class RunCreate(RequestModel):
    agent_id: UUID
    name: str = Field(default="", max_length=200, examples=["Prompt v3 baseline"])
    kind: Literal["matrix", "dry_run"] = "matrix"
    scenario_ids: list[UUID] = Field(min_length=1)
    persona_ids: list[UUID] = Field(min_length=1)
    noise_profile_ids: list[UUID] = Field(min_length=1)
    repeats: int = Field(default=1, ge=1, le=20)
    config: RunConfig = Field(default_factory=RunConfig)
    confirm_over_budget: bool = False


class RegressionRunCreate(RequestModel):
    agent_id: UUID
    name: str = Field(default="", max_length=200)
    statuses: list[RegressionStatus] = Field(default=["blocking"], min_length=1)
    config: RunConfig = Field(default_factory=RunConfig)
    confirm_over_budget: bool = False


class RunEstimate(BaseModel):
    tts_seconds: float
    stt_seconds: float
    judge_calls: int
    caller_llm_calls: int
    est_cost: float


class RunCreated(BaseModel):
    id: UUID
    status: RunStatus
    item_count: int
    estimate: RunEstimate


class RunEstimateOut(BaseModel):
    """``POST /runs:estimate``: the wizard's dry run of ``POST /runs`` (FR-RN-2)."""

    item_count: int
    estimate: RunEstimate
    remaining_budget: float | None = None
    over_budget: bool = False


class RunProgress(BaseModel):
    total: int = 0
    queued: int = 0
    in_progress: int = 0
    evaluated: int = 0
    error: int = 0


class RunSummary(BaseModel):
    """Filled by the finalizer; fields are null until enough items are evaluated."""

    pass_rate: float | None = None
    critical_failures: int | None = None
    needs_review: int | None = None
    score_mean: float | None = None
    latency_p50_ms: int | None = None
    latency_p95_ms: int | None = None
    barge_in_honoured_rate: float | None = None
    top_failure_types: list[tuple[str, int]] = Field(default_factory=list)
    suite_passed: bool | None = Field(default=None, description="regression runs only")
    score_distribution: list[int] = Field(
        default_factory=list,
        description="FR-DB-2: counts of evaluated calls per 10-point score bucket "
        "(0-9, 10-19, ..., 90-100); empty until evaluations exist",
    )


class RunOut(BaseModel):
    id: UUID
    agent_id: UUID
    name: str = ""
    kind: RunKind
    status: RunStatus
    progress: RunProgress
    summary: RunSummary = Field(default_factory=RunSummary)
    estimated_cost: float | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunItemOut(BaseModel):
    """One row of the matrix view."""

    id: UUID
    scenario: str
    persona: str
    noise_profile: str
    status: RunItemStatus
    call_id: UUID | None = None
    overall_score: float | None = None
    passed: bool | None = None
    critical_failure: bool | None = None


class RunCompareCell(BaseModel):
    scenario: str
    persona: str
    profile: str
    base_score: float | None = None
    head_score: float | None = None
    delta: float | None = None
    newly_failing: bool = False


class RunCompareSummary(BaseModel):
    regressed: int
    improved: int
    unchanged: int


class RunCompareOut(BaseModel):
    cells: list[RunCompareCell]
    summary: RunCompareSummary


# --- Server-Sent Events of GET /runs/{id}/events ---------------------------------------------
# These are the `data:` payloads. They are added to the OpenAPI components so the generated
# clients get types for them (an SSE body itself cannot be described in OpenAPI).


class SseSnapshot(BaseModel):
    """``event: snapshot`` - sent first, and again after every reconnect."""

    run: RunOut
    items: list[RunItemOut]


class SseItemStatus(BaseModel):
    """``event: item.status``"""

    run_item_id: UUID
    status: RunItemStatus
    scenario: str | None = None
    persona: str | None = None


class SseCallEvaluated(BaseModel):
    """``event: call.evaluated``"""

    run_item_id: UUID
    call_id: UUID
    overall_score: float
    passed: bool
    critical_failure: bool


class SseRunCompletedSummary(BaseModel):
    pass_rate: float | None = None
    critical_failures: int | None = None


class SseRunCompleted(BaseModel):
    """``event: run.completed``"""

    run_id: UUID
    summary: SseRunCompletedSummary


SSE_EVENT_MODELS: tuple[type[BaseModel], ...] = (
    SseSnapshot,
    SseItemStatus,
    SseCallEvaluated,
    SseRunCompleted,
)
