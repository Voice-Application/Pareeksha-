"""DeepSeek provider (OpenAI-compatible chat completions, JSON mode).

Facts verified against api-docs.deepseek.com (NOTES.md, TL-01): ``response_format`` supports only
``json_object`` (the prompt must say "json" and show an example); content may come back empty;
thinking mode is on by default and ignores ``temperature``, so it is disabled unless requested.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

import httpx

from pareeksha.llm._http import classify_status, classify_transport
from pareeksha.llm._retry import call_with_retries
from pareeksha.llm.base import (
    ChatMessage,
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMPermanentError,
    LLMProvider,
    LLMProviderName,
    LLMRetryableError,
    LLMUsage,
)
from pareeksha.llm.config import DEEPSEEK_DEFAULT_BASE_URL

_SCHEMA_INSTRUCTION = (
    "Respond with a single valid json object and nothing else (no markdown fences). "
    "It must validate against this JSON Schema:\n{schema}"
)


class DeepSeekProvider(LLMProvider):
    name: ClassVar[LLMProviderName] = LLMProviderName.DEEPSEEK

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEEPSEEK_DEFAULT_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        backoff_s: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._client = http_client or httpx.AsyncClient()
        self._owns_client = http_client is None
        self._backoff_s = backoff_s
        self._sleep = sleep

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        body = self._body(request)
        return await call_with_retries(
            lambda: self._once(request, body), base_delay_s=self._backoff_s, sleep=self._sleep
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- internals ------------------------------------------------------------------------

    @staticmethod
    def _messages(request: JSONCompletionRequest) -> list[ChatMessage]:
        messages = list(request.messages)
        if request.json_schema is not None:
            schema = json.dumps(request.json_schema, ensure_ascii=False)
            messages.insert(
                0, ChatMessage(role="system", content=_SCHEMA_INSTRUCTION.format(schema=schema))
            )
        elif not any("json" in m.content.lower() for m in messages):
            messages.insert(
                0, ChatMessage(role="system", content="Respond with a single valid json object.")
            )
        return messages

    def _body(self, request: JSONCompletionRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [m.model_dump() for m in self._messages(request)],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "enabled" if request.thinking else "disabled"},
            "stream": False,
        }
        if not request.thinking:
            body["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            body["max_tokens"] = request.max_output_tokens
        return body

    async def _once(
        self, request: JSONCompletionRequest, body: dict[str, Any]
    ) -> JSONCompletionResult:
        started = time.monotonic()
        try:
            response = await self._client.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=request.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise classify_transport(exc, "deepseek") from exc
        error = classify_status(response, "deepseek")
        if error is not None:
            raise error
        try:
            data = response.json()
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMRetryableError(f"deepseek returned an unreadable response: {exc}") from exc
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            raise LLMPermanentError("deepseek blocked the content (finish_reason=content_filter)")
        if not text.strip():
            raise LLMRetryableError("deepseek returned empty content in JSON mode")
        return JSONCompletionResult(
            provider=self.name,
            model=str(data.get("model") or request.model),
            text=text,
            usage=LLMUsage(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                cached_input_tokens=int(usage.get("prompt_cache_hit_tokens", 0)),
            ),
            finish_reason=finish,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
