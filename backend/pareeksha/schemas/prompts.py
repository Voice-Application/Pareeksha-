"""Prompt-agent versions (docs/superpowers/specs/2026-11-06-prompt-and-rag-testing-design.md)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from pareeksha.schemas.common import RequestModel
from pareeksha.schemas.rag import RagConfig

ProviderName = Literal[
    "openai", "openai_compatible", "deepseek", "groq", "mistral", "ollama", "anthropic", "gemini"
]


class MockCase(RequestModel):
    when: dict[str, Any]
    result: dict[str, Any]


class MockSpec(RequestModel):
    mode: Literal["static", "by_args", "simulated"] = "static"
    result: dict[str, Any] = Field(default_factory=dict)
    cases: list[MockCase] = Field(default_factory=list)


class PromptTool(RequestModel):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str = ""
    parameters: dict[str, Any] = Field(description='JSON Schema; must have "type": "object"')
    mock: MockSpec = Field(default_factory=MockSpec)

    @field_validator("parameters")
    @classmethod
    def _object_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        """Require an object JSON Schema with schema-valued ``properties`` and a name-list
        ``required``.
        """
        if v.get("type") != "object":
            raise ValueError('parameters must be a JSON Schema with "type": "object"')
        props = v.get("properties", {})
        if not isinstance(props, dict) or not all(isinstance(p, dict) for p in props.values()):
            raise ValueError('parameters "properties" must be an object of JSON Schemas')
        required = v.get("required", [])
        if not isinstance(required, list) or not all(isinstance(r, str) for r in required):
            raise ValueError('parameters "required" must be a list of property names')
        return v


class _PromptVersionFields(RequestModel):
    system_prompt: str = Field(min_length=1, max_length=100_000)
    provider: ProviderName
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=2)
    tools: list[PromptTool] = Field(default_factory=list, max_length=64)
    max_tool_rounds: int = Field(default=5, ge=1, le=10)
    rag_config: RagConfig | None = None
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _unique_tool_names(self) -> _PromptVersionFields:
        """Reject a version that declares two tools with the same name."""
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        return self


class PromptVersionCreate(_PromptVersionFields):
    @model_validator(mode="after")
    def _compatible_needs_base_url(self) -> PromptVersionCreate:
        """Require a non-blank ``base_url`` for ``openai_compatible`` (checked on create only)."""
        # create-only: versions stored before this rule must still load
        if self.provider == "openai_compatible" and not (self.base_url or "").strip():
            raise ValueError("openai_compatible requires a base_url")
        return self


class PromptVersionOut(_PromptVersionFields):
    id: UUID
    agent_id: UUID
    version: int
    content_hash: str
    created_at: datetime


def content_hash(body: PromptVersionCreate) -> str:
    data = body.model_dump(mode="json", exclude={"note"})
    if data["rag_config"] is None:
        del data["rag_config"]  # versions without RAG keep their pre-RAG hash
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
