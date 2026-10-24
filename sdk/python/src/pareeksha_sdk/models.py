"""Typed response models. Unknown fields are kept (``extra="allow"``) so a newer server never
breaks an older SDK; the fields below are the stable part of docs/06-api-spec.md."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class Agent(_Model):
    id: UUID
    name: str
    adapter: str = "audio_v1"
    archived: bool = False


class Named(_Model):
    """Scenario / persona / noise profile: the SDK needs the id and the name or title."""

    id: UUID
    name: str | None = None
    title: str | None = None
    tags: list[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        return self.name or self.title or str(self.id)


class RunProgress(_Model):
    total: int = 0
    queued: int = 0
    in_progress: int = 0
    evaluated: int = 0
    error: int = 0


class RunSummary(_Model):
    pass_rate: float | None = None
    critical_failures: int | None = None
    needs_review: int | None = None
    score_mean: float | None = None
    top_failure_types: list[tuple[str, int]] = Field(default_factory=list)
    suite_passed: bool | None = None


RunStatus = Literal["draft", "queued", "running", "completed", "partial", "cancelled", "failed"]
FINAL_RUN_STATUSES: frozenset[str] = frozenset({"completed", "partial", "cancelled", "failed"})


class Run(_Model):
    id: UUID
    status: RunStatus
    kind: str = "matrix"
    name: str = ""
    progress: RunProgress = Field(default_factory=RunProgress)
    summary: RunSummary = Field(default_factory=RunSummary)

    @property
    def is_final(self) -> bool:
        return self.status in FINAL_RUN_STATUSES


class RunCreated(_Model):
    id: UUID
    status: RunStatus
    item_count: int = 0
    estimate: dict[str, Any] = Field(default_factory=dict)


class RunItem(_Model):
    id: UUID
    scenario: str
    persona: str
    noise_profile: str
    status: str
    call_id: UUID | None = None
    overall_score: float | None = None
    passed: bool | None = None
    critical_failure: bool | None = None


class Call(_Model):
    id: UUID
    status: Literal["in_progress", "transcribing", "completed", "error"]
    evaluation: dict[str, Any] | None = None


class CallRef(_Model):
    call_id: UUID


class DeadLetter(_Model):
    id: UUID
    event_id: UUID
    original_topic: str
    consumer_group: str
    error: str
    attempts: int
    status: str = "open"


class Health(_Model):
    db: str
    kafka: str
