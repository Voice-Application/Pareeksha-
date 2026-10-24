"""Regression tests (docs/06-api-spec.md section 12; FR-RG-1, FR-RG-2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from pareeksha.schemas.common import RequestModel
from pareeksha.schemas.runs import RegressionStatus


class RegressionTestOut(BaseModel):
    id: UUID
    agent_id: UUID
    scenario_id: UUID
    scenario_title: str
    persona_id: UUID | None = None
    noise_profile_id: UUID | None = None
    source_call_id: UUID | None = None
    failure_type: str
    status: RegressionStatus
    baseline_score: float
    tolerance: float
    notes: str = ""
    created_at: datetime
    last_run_id: UUID | None = None
    last_score: float | None = None
    last_passed: bool | None = Field(
        default=None, description="score >= baseline - tolerance and no critical failure"
    )


class RegressionTestUpdate(RequestModel):
    status: RegressionStatus | None = None
    baseline_score: float | None = Field(default=None, ge=0, le=100)
    tolerance: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = None
