"""LLM provider interface. FROZEN CONTRACT (owner-approved 2026-10-23, see CHANGELOG.md).

All LLM uses in Pareeksha are text-only JSON completions: caller brain, judge, scenario
generation, role detection and ASR-intent checks. Providers (DeepSeek default, Gemini supported)
implement :class:`LLMProvider`; they are written by EVAL-01. The higher-level client (schema
validation, one repair retry, usage logging, prompt hashing) is built on top of this interface and
is provider-independent.

Provider notes (verified against api-docs.deepseek.com, 2026-10-23; see NOTES.md):
- DeepSeek supports ``response_format={"type": "json_object"}`` only (no server-side JSON Schema),
  needs the word "json" and an example in the prompt, and may occasionally return empty content.
  A provider must therefore put ``json_schema`` into the prompt and the caller validates the result.
- DeepSeek thinking mode is on by default and ignores ``temperature``; deterministic calls (judge,
  temperature 0) must disable it, which is what ``thinking=False`` (the default) means.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMProviderName(StrEnum):
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"


class LLMPurpose(StrEnum):
    """What the call is for (usage logging and model/temperature selection)."""

    CALLER = "caller"
    JUDGE = "judge"
    SCENARIO_GEN = "scenario_gen"
    ROLE_DETECT = "role_detect"
    ASR_INTENT = "asr_intent"


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class LLMUsage(BaseModel):
    """Token usage as reported by the provider (used for ``api_usage`` and cost)."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    #: Part of ``input_tokens`` served from the provider's prompt cache, when reported.
    cached_input_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class JSONCompletionRequest(BaseModel):
    """One JSON-mode completion."""

    model_config = ConfigDict(extra="forbid")

    purpose: LLMPurpose
    #: Exact pinned model ID (never a "latest" alias).
    model: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    #: JSON Schema of the expected object. Providers use native schema enforcement where they have
    #: it (Gemini) or embed it in the prompt (DeepSeek); the caller always validates the result.
    json_schema: dict[str, Any] | None = None
    max_output_tokens: int | None = Field(default=None, ge=1)
    #: Provider reasoning ("thinking") mode. Off by default so temperature is honoured.
    thinking: bool = False
    timeout_s: float = Field(default=60.0, gt=0)


class JSONCompletionResult(BaseModel):
    """Raw provider output; JSON parsing and schema validation are the caller's job."""

    provider: LLMProviderName
    model: str
    #: The model's text, expected to be one JSON document.
    text: str
    usage: LLMUsage
    finish_reason: str | None = None
    latency_ms: int = Field(ge=0)


class LLMError(Exception):
    """Base class for provider failures."""


class LLMRetryableError(LLMError):
    """Timeouts, connection errors, 5xx, 429, empty JSON-mode content.

    The provider retries these 3 times with backoff; if it still fails the consumer framework
    routes the message through the retry topics.
    """

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class LLMPermanentError(LLMError):
    """Bad credentials, 4xx, unsupported model, safety block. Not retried (DLQ)."""


class LLMProvider(ABC):
    """A text-only JSON completion backend."""

    name: ClassVar[LLMProviderName]

    @abstractmethod
    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        """Run one completion in JSON mode and return the text plus token usage."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release HTTP clients / sessions. Idempotent."""
