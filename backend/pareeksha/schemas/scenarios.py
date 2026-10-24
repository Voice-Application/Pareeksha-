"""Scenarios and scenario drafts (docs/06-api-spec.md section 2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from pareeksha.schemas.common import RequestModel

ScenarioSource = Literal["manual", "generated", "promoted"]
DraftStatus = Literal["pending", "ready", "failed"]


class ScenarioCreate(RequestModel):
    agent_id: UUID | None = Field(default=None, description="null = reusable across agents")
    title: str = Field(min_length=1, max_length=300)
    caller_goal: str = Field(min_length=1)
    fixtures: dict[str, Any] = Field(default_factory=dict, description="synthetic facts only")
    reveal_rules: str = ""
    success_criteria: str = Field(min_length=1)
    must_say: list[str] = Field(default_factory=list)
    must_not_say: list[str] = Field(default_factory=list)
    expected_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    caller_speaks_first: bool = False
    max_turns: int = Field(default=15, ge=1, le=60)
    tags: list[str] = Field(default_factory=list)


class ScenarioUpdate(RequestModel):
    agent_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=300)
    caller_goal: str | None = Field(default=None, min_length=1)
    fixtures: dict[str, Any] | None = None
    reveal_rules: str | None = None
    success_criteria: str | None = Field(default=None, min_length=1)
    must_say: list[str] | None = None
    must_not_say: list[str] | None = None
    expected_tool_calls: list[dict[str, Any]] | None = None
    caller_speaks_first: bool | None = None
    max_turns: int | None = Field(default=None, ge=1, le=60)
    tags: list[str] | None = None


class ScenarioOut(ScenarioCreate):
    id: UUID
    source: ScenarioSource = "manual"
    source_call_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ScenarioBulkCreate(RequestModel):
    """``POST /scenarios:bulk`` - save reviewed drafts."""

    scenarios: list[ScenarioCreate] = Field(min_length=1, max_length=100)
    source: ScenarioSource = "generated"


class ScenarioBulkResult(BaseModel):
    items: list[ScenarioOut]


class ScenarioGenerateRequest(RequestModel):
    count: int = Field(ge=1, le=50, examples=[10])
    mix: dict[str, int] = Field(
        default_factory=dict, examples=[{"happy_path": 3, "edge_case": 4, "adversarial": 3}]
    )


class DraftAccepted(BaseModel):
    draft_id: UUID


class ScenarioDraftOut(BaseModel):
    """Drafts are not saved scenarios; the web app shows them for review, then bulk-saves."""

    id: UUID
    agent_id: UUID
    status: DraftStatus
    request: ScenarioGenerateRequest
    drafts: list[ScenarioCreate] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
