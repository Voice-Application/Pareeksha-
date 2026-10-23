"""Dialect datasets and reports (docs/06-api-spec.md section 5)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from pareeksha.schemas.common import RequestModel


class DatasetCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200, examples=["Kannada dialects v1"])
    description: str = ""


class DatasetOut(BaseModel):
    id: UUID
    name: str
    description: str = ""
    sample_count: int = 0
    created_at: datetime


class RejectedRow(BaseModel):
    row: int = Field(description="1-based manifest row")
    reason: str = Field(examples=["consent must be true"])


class SamplesUploadResult(BaseModel):
    accepted: int
    rejected: list[RejectedRow] = Field(default_factory=list)


class DialectEvaluateRequest(RequestModel):
    noise_profile_ids: list[UUID] = Field(min_length=1)
    engines: list[str] = Field(min_length=1, examples=[["gnani-prisma"]])


class DialectEvaluateAccepted(BaseModel):
    report_id: UUID
    expected_results: int


class ReportProgress(BaseModel):
    done: int
    expected_results: int


class EngineAggregate(BaseModel):
    n: int
    wer: float
    wer_ci: tuple[float, float]
    cer: float
    entity_acc: float | None = None
    intent_preserved_rate: float | None = None


class TopError(BaseModel):
    ref: str
    hyp: str
    count: int


class DialectReportOut(BaseModel):
    id: UUID
    dataset_id: UUID
    progress: ReportProgress
    #: ``{dialect: {condition: {engine: EngineAggregate}}}``; empty until aggregation finishes.
    aggregates: dict[str, dict[str, dict[str, EngineAggregate]]] = Field(default_factory=dict)
    top_errors: list[TopError] = Field(default_factory=list)
    bias_suggestions: list[str] = Field(default_factory=list)
    html: str | None = Field(default=None, examples=["/api/v1/dialect-reports/<id>/html"])
    created_at: datetime | None = None


class DialectReportSummaryOut(BaseModel):
    """One row of ``GET /dialect-reports``."""

    id: UUID
    dataset_id: UUID
    engines: list[str]
    conditions: list[UUID]
    progress: ReportProgress
    created_at: datetime


class ClipResultOut(BaseModel):
    """One clip x condition x engine result for the worst-clips drill-down (FR-DB-4)."""

    sample_id: UUID
    dialect_label: str
    condition: str = Field(description="noise profile name")
    engine: str
    reference_text: str
    hypothesis_text: str
    wer: float
    cer: float
    entity_total: int = 0
    entity_correct: int = 0
    intent_preserved: bool | None = None
    audio_url: str | None = None
