"""Shared API models: error envelope, pagination, enums reused across resources."""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

AdapterType = Literal["audio_v1", "pipecat", "livekit", "vapi"]
Scope = Literal["read", "runs:write", "audits:write", "admin"]
CallSource = Literal["simulation", "upload", "import"]


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected (400 validation_error)."""

    model_config = ConfigDict(extra="forbid")


class ErrorBody(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """``{ "error": { "code", "message", "details" } }`` for every non-2xx response."""

    error: ErrorBody


class Page(BaseModel, Generic[T]):
    """List response: ``{ "items": [...], "next_cursor": "..." | null }``."""

    items: list[T]
    next_cursor: str | None = None


class CallRef(BaseModel):
    """Body of a 202 that points at a call to poll (``GET /calls/{call_id}``)."""

    call_id: UUID


class Disclosure(BaseModel):
    id: str
    text: str
    regex: str | None = None
    within_turns: int = Field(default=2, ge=1)


class ForbiddenPhrase(BaseModel):
    id: str
    text: str
    regex: str | None = None


class ExpectedTool(BaseModel):
    name: str
    description: str = ""
    args_schema: dict[str, Any] | None = None
