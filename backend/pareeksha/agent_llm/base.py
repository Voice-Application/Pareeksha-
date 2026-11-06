"""Shared types and HTTP plumbing for tool-calling chat providers (the model under test)."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCallReq:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str
    #: Opaque provider state to echo back on the next request (e.g. Gemini thought signature).
    provider_data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentMessage:
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: tuple[ToolCallReq, ...] = ()
    tool_call_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ChatReply:
    text: str
    tool_calls: tuple[ToolCallReq, ...]
    input_tokens: int
    output_tokens: int
    latency_ms: int


class AgentLLMError(Exception):
    """Provider call failed. The message never contains the API key, headers or request body."""

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class ChatProvider(Protocol):
    async def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        model: str,
        temperature: float,
        timeout_s: float = 60.0,
    ) -> ChatReply: ...


def parse_args(raw: str) -> dict[str, Any]:
    """Tool-call arguments as a dict; invalid JSON (or a non-object) becomes ``{"_raw": raw}``."""
    try:
        parsed = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": raw}


def _error_text(resp: httpx.Response, api_key: str | None) -> str:
    try:
        data = resp.json()
        err = data.get("error", data) if isinstance(data, dict) else data
        msg = err.get("message") if isinstance(err, dict) else err
        text = str(msg or "")
    except ValueError:
        text = resp.text
    text = text[:200]
    return text.replace(api_key, "***") if api_key else text


async def post_json(
    http: httpx.AsyncClient | None,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    *,
    timeout_s: float,
    api_key: str | None,
) -> tuple[dict[str, Any], int]:
    """POST JSON; return ``(response json, latency_ms)`` or raise a key-free ``AgentLLMError``."""
    start = time.monotonic()
    try:
        if http is None:
            async with httpx.AsyncClient(follow_redirects=False) as client:
                resp = await client.post(url, headers=headers, json=body, timeout=timeout_s)
        else:
            resp = await http.post(url, headers=headers, json=body, timeout=timeout_s)
    except httpx.TimeoutException as exc:
        raise AgentLLMError("provider request timed out", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise AgentLLMError(
            f"provider request failed: {type(exc).__name__}", retryable=True
        ) from exc
    latency_ms = int((time.monotonic() - start) * 1000)
    if resp.status_code >= 400:
        raise AgentLLMError(
            f"provider returned HTTP {resp.status_code}: {_error_text(resp, api_key)}",
            status=resp.status_code,
            retryable=resp.status_code in (408, 409, 429) or resp.status_code >= 500,
        )
    try:
        data = resp.json()
    except ValueError as exc:
        raise AgentLLMError(
            "provider returned a non-JSON response", status=resp.status_code
        ) from exc
    if not isinstance(data, dict):
        raise AgentLLMError("provider returned an unexpected response", status=resp.status_code)
    return data, latency_ms
