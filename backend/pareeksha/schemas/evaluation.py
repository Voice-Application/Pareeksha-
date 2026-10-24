"""Judge output schema (docs/08-evaluation-rubric.md section 5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pareeksha.schemas.calls import FailureType

__all__ = ["DimensionScore", "Dimensions", "FailureType", "JudgeOutput"]


class DimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: int = Field(ge=0, le=4)
    evidence_turns: list[int] = Field(default_factory=list)
    reason: str = Field(max_length=300)


class Dimensions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_completion: DimensionScore
    policy_compliance: DimensionScore
    factual_accuracy: DimensionScore
    language_handling: DimensionScore
    conversation_flow: DimensionScore
    empathy_tone: DimensionScore
    escalation: DimensionScore


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: Dimensions
    critical_failure: bool
    needs_human_review: bool
    failure_types: list[FailureType] = Field(default_factory=list)
    summary: str = Field(max_length=400)
    confidence: Literal["high", "medium", "low"]
