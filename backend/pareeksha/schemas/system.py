"""Calibration, usage, health, metrics, DLQ, API keys (docs/06-api-spec.md sections 6, 9, 10)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from pareeksha.schemas.common import RequestModel, Scope
from pareeksha.speech.registry import ProviderStatus


class CalibrationOut(BaseModel):
    n: int
    kappa_pass_fail: float | None = None
    spearman_overall: float | None = None
    dimension_mae: dict[str, float] = Field(default_factory=dict)


class UsageRow(BaseModel):
    provider: Literal["gnani", "gemini", "deepseek", "other"]
    operation: str = Field(examples=["tts", "stt_batch", "llm_judge"])
    unit_type: Literal["audio_seconds", "characters", "tokens"]
    units: float
    est_cost: float | None = None


class UsageOut(BaseModel):
    items: list[UsageRow]
    credits_used: float
    budget_credits: float | None = None
    remaining_budget: float | None = None


class HealthOut(BaseModel):
    """Each value is ``"ok"`` or ``"down: <reason>"``."""

    db: str
    kafka: str


class SpeechProvidersOut(BaseModel):
    items: list[ProviderStatus]


class MetricsSummary(BaseModel):
    consumer_lag: dict[str, int] = Field(examples=[{"simulator": 4, "evaluator": 0}])
    outbox_backlog: int
    dlq_open: int
    credits_used: float


DeadLetterStatus = Literal["open", "replayed", "discarded"]


class DeadLetterOut(BaseModel):
    id: UUID
    event_id: UUID
    original_topic: str
    consumer_group: str
    error: str
    attempts: int
    status: DeadLetterStatus = "open"
    failed_at: datetime
    envelope: dict[str, Any]


class ApiKeyCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200, examples=["github-actions"])
    scopes: list[Scope] = Field(default=["read"], min_length=1)


class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    prefix: str = Field(examples=["pk_live_ab12cd34"])
    scopes: list[Scope]
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    """Returned once, on creation. The full key is never retrievable again."""

    key: str = Field(description="full key, shown once", examples=["pk_live_..."])
