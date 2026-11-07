"""Per-project LLM settings (docs/06-api-spec.md section 13)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from pareeksha.schemas.common import RequestModel

LLMProviderChoice = Literal["deepseek", "gemini", "openai_compatible"]


class LLMSettingsUpdate(RequestModel):
    """``PUT /settings/llm``: replaces the project's settings; only ``api_key`` can be omitted to
    keep the stored key."""

    provider: LLMProviderChoice
    base_url: str | None = Field(
        default=None,
        max_length=500,
        description="openai_compatible only: https URL of the API root (SSRF-checked)",
    )
    judge_model: str | None = Field(default=None, min_length=1, max_length=200)
    caller_model: str | None = Field(default=None, min_length=1, max_length=200)
    designer_model: str | None = Field(
        default=None, min_length=1, max_length=200, description="default: the judge model"
    )
    api_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        repr=False,
        description="write-only; omitted keeps the stored key",
    )


class LLMSettingsOut(BaseModel):
    provider: LLMProviderChoice
    base_url: str | None
    judge_model: str | None
    caller_model: str | None
    designer_model: str | None
    api_key_set: bool
    api_key_last4: str | None
    source: Literal["project", "environment"]


class LLMTestResult(BaseModel):
    ok: bool
    provider: LLMProviderChoice
    model: str | None
    latency_ms: int | None
    error: str | None
