"""Shared types and HTTP plumbing for tool-calling chat providers (the model under test)."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from pareeksha.agent_llm.url_guard import allow_private_urls, is_operator_ollama
from pareeksha.integrations.ssrf import SSRFError, buffered_response, safe_request

#: Largest provider response body accepted (enforced while streaming).
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


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
    """Provider call failed. The message never contains the API key, headers, request body or
    the provider's own error text; that text (key-redacted, truncated) is kept separately in
    ``provider_message`` for retry decisions and must not be shown or persisted."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        provider_message: str = "",
    ):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.provider_message = provider_message


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


def object_args(value: Any) -> tuple[dict[str, Any], str]:
    """``(arguments, raw_arguments)`` for an already-decoded tool input (Anthropic ``input``,
    Gemini ``args``). Missing is ``{}``; a non-object becomes ``{"_raw": raw}`` like
    ``parse_args``, so the mock layer answers ``invalid_arguments``."""
    if value is None:
        return {}, "{}"
    raw = json.dumps(value)
    return (value, raw) if isinstance(value, dict) else ({"_raw": raw}, raw)


def _error_text(resp: httpx.Response, api_key: str | None) -> str:
    """The provider's error message from ``resp``, with ``api_key`` redacted, cut to 200 chars."""
    try:
        data = resp.json()
        err = data.get("error", data) if isinstance(data, dict) else data
        msg = err.get("message") if isinstance(err, dict) else err
        text = str(msg or "")
    except ValueError:
        text = resp.text
    # redact before truncating so a key straddling the cut cannot leave a prefix behind
    if api_key:
        text = text.replace(api_key, "***")
    return text[:200]


async def _send(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout_s: float
) -> httpx.Response:
    """The one production path to a provider: ``safe_request`` (https only, public addresses,
    connection pinned to the validated IP, no redirects, size cap). ``AGENT_LLM_ALLOW_PRIVATE_URLS``
    is the operator's opt-in for local/self-hosted servers, and the operator's ``OLLAMA_BASE_URL``
    is trusted on its own: plain httpx, still no redirects and the same size cap."""
    content = json.dumps(body).encode()
    headers = {**headers, "Content-Type": "application/json"}
    if not (allow_private_urls() or is_operator_ollama(url)):
        return await safe_request(
            "POST",
            url,
            headers=headers,
            content=content,
            timeout_s=timeout_s,
            max_bytes=MAX_RESPONSE_BYTES,
        )
    async with (
        httpx.AsyncClient(follow_redirects=False, timeout=timeout_s) as client,
        client.stream("POST", url, headers=headers, content=content) as response,
    ):
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise SSRFError(f"response larger than {MAX_RESPONSE_BYTES} bytes")
            chunks.append(chunk)
        return buffered_response(response, b"".join(chunks))


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
            resp = await _send(url, headers, body, timeout_s)
        else:
            resp = await http.post(url, headers=headers, json=body, timeout=timeout_s)
    except SSRFError as exc:
        raise AgentLLMError(f"provider URL not allowed: {exc}", retryable=False) from exc
    except httpx.InvalidURL as exc:  # not an HTTPError subclass
        raise AgentLLMError(f"provider URL is invalid: {exc}", retryable=False) from exc
    except httpx.TimeoutException as exc:
        raise AgentLLMError("provider request timed out", retryable=True) from exc
    except httpx.HTTPError as exc:
        # no chaining: e.g. LocalProtocolError's text quotes the offending header (the API key)
        raise AgentLLMError(
            f"provider request failed: {type(exc).__name__}", retryable=True
        ) from None
    latency_ms = int((time.monotonic() - start) * 1000)
    if resp.is_redirect:
        raise AgentLLMError(
            f"provider redirected (HTTP {resp.status_code}); redirects are not followed",
            status=resp.status_code,
        )
    if resp.status_code >= 400:
        raise AgentLLMError(
            f"provider returned HTTP {resp.status_code}",
            status=resp.status_code,
            retryable=resp.status_code in (408, 409, 429) or resp.status_code >= 500,
            provider_message=_error_text(resp, api_key),
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
