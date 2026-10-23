"""Agents (docs/06-api-spec.md section 1)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from pareeksha.schemas.common import (
    AdapterType,
    Disclosure,
    ExpectedTool,
    ForbiddenPhrase,
    RequestModel,
)


class AgentCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200, examples=["EMI Reminder Bot"])
    description: str = ""
    adapter: AdapterType = "audio_v1"
    adapter_config: dict[str, object] = Field(default_factory=dict)
    endpoint_url: str = Field(min_length=1, examples=["ws://mock-agent:8765/ws"])
    languages: list[str] = Field(default_factory=list, examples=[["kn-IN", "hi-IN", "en-IN"]])
    glass_box: bool = False
    mandatory_disclosures: list[Disclosure] = Field(default_factory=list)
    forbidden_phrases: list[ForbiddenPhrase] = Field(default_factory=list)
    expected_tools: list[ExpectedTool] = Field(default_factory=list)
    bias_list: list[str] = Field(default_factory=list)
    max_call_seconds: int = Field(default=300, ge=10, le=1800)


class AgentUpdate(RequestModel):
    """PATCH: only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    adapter: AdapterType | None = None
    adapter_config: dict[str, object] | None = None
    endpoint_url: str | None = Field(default=None, min_length=1)
    languages: list[str] | None = None
    glass_box: bool | None = None
    mandatory_disclosures: list[Disclosure] | None = None
    forbidden_phrases: list[ForbiddenPhrase] | None = None
    expected_tools: list[ExpectedTool] | None = None
    bias_list: list[str] | None = None
    max_call_seconds: int | None = Field(default=None, ge=10, le=1800)


class AgentOut(AgentCreate):
    id: UUID
    archived: bool = False
    created_at: datetime
    updated_at: datetime


class TestConnectionResult(BaseModel):
    """``ok=true`` carries the timing fields; ``ok=false`` carries ``error`` and ``detail``."""

    __test__ = False

    ok: bool
    first_audio_ms: int | None = None
    protocol: str | None = None
    glass_box_messages_seen: bool | None = None
    error: str | None = Field(default=None, examples=["timeout"])
    detail: str | None = None
