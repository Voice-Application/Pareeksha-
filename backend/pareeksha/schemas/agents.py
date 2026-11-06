"""Agents (docs/06-api-spec.md section 1)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from pareeksha.schemas.common import (
    AdapterType,
    Disclosure,
    ExpectedTool,
    ForbiddenPhrase,
    RequestModel,
)


def _check_speech_override(value: dict[str, object] | None) -> dict[str, object] | None:
    """``adapter_config.speech`` (per-agent STT/TTS provider) must name known providers."""
    from pareeksha.speech.agent_config import speech_selection
    from pareeksha.speech.base import SpeechConfigError

    try:
        speech_selection(value)
    except SpeechConfigError as exc:
        raise ValueError(str(exc)) from exc
    return value


class _AgentFields(RequestModel):
    name: str = Field(min_length=1, max_length=200, examples=["EMI Reminder Bot"])
    description: str = ""
    adapter: AdapterType = "audio_v1"
    adapter_config: dict[str, object] = Field(default_factory=dict)
    languages: list[str] = Field(default_factory=list, examples=[["kn-IN", "hi-IN", "en-IN"]])
    glass_box: bool = False
    mandatory_disclosures: list[Disclosure] = Field(default_factory=list)
    forbidden_phrases: list[ForbiddenPhrase] = Field(default_factory=list)
    expected_tools: list[ExpectedTool] = Field(default_factory=list)
    bias_list: list[str] = Field(default_factory=list)
    max_call_seconds: int = Field(default=300, ge=10, le=1800)

    _speech = field_validator("adapter_config")(_check_speech_override)


class AgentCreate(_AgentFields):
    #: Optional only for ``adapter == "prompt"`` (the server stores ``prompt://<agent_id>``).
    endpoint_url: str | None = Field(
        default=None, min_length=1, examples=["ws://mock-agent:8765/ws"]
    )
    #: Write-only provider secrets (``{"api_key": ...}``); stored encrypted, never returned.
    adapter_secrets: dict[str, str] | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _endpoint_required(self) -> AgentCreate:
        if self.endpoint_url is None and self.adapter != "prompt":
            raise ValueError("endpoint_url is required")
        return self


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
    #: Write-only; ``{}`` clears the stored secrets.
    adapter_secrets: dict[str, str] | None = Field(default=None, exclude=True)

    _speech = field_validator("adapter_config")(_check_speech_override)


class AgentOut(_AgentFields):
    id: UUID
    endpoint_url: str
    has_adapter_secrets: bool = False
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
