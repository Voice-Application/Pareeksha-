"""Gemini provider (REST ``models/{model}:generateContent``, native JSON-schema output).

Field names from ai.google.dev/api/generate-content (checked 2026-10-24): auth header
``x-goog-api-key``; ``systemInstruction``; ``generationConfig.responseMimeType`` /
``responseJsonSchema`` / ``temperature`` / ``maxOutputTokens``; ``usageMetadata``
(``promptTokenCount``, ``cachedContentTokenCount``, ``candidatesTokenCount``,
``thoughtsTokenCount``); ``promptFeedback.blockReason``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

import httpx

from pareeksha.llm._http import classify_status, classify_transport
from pareeksha.llm._retry import call_with_retries
from pareeksha.llm.base import (
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMPermanentError,
    LLMProvider,
    LLMProviderName,
    LLMRetryableError,
    LLMUsage,
)

GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: Finish reasons that mean the model refused or was filtered (not worth retrying).
_BLOCKED_FINISH = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"}


class GeminiProvider(LLMProvider):
    name: ClassVar[LLMProviderName] = LLMProviderName.GEMINI

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = GEMINI_DEFAULT_BASE_URL,
        http_client: httpx.AsyncClient | None = None,
        backoff_s: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
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
    def _body(request: JSONCompletionRequest) -> dict[str, Any]:
        system = [m.content for m in request.messages if m.role == "system"]
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages
            if m.role != "system"
        ]
        if not contents:  # Gemini needs at least one user turn
            contents = [{"role": "user", "parts": [{"text": "\n\n".join(system)}]}]
            system = []
        config: dict[str, Any] = {
            "responseMimeType": "application/json",
            "temperature": request.temperature,
        }
        if request.json_schema is not None:
            config["responseJsonSchema"] = request.json_schema
        if request.max_output_tokens is not None:
            config["maxOutputTokens"] = request.max_output_tokens
        if not request.thinking:
            config["thinkingConfig"] = {"thinkingBudget": 0}
        body: dict[str, Any] = {"contents": contents, "generationConfig": config}
        if system:
            body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
        return body

    async def _once(
        self, request: JSONCompletionRequest, body: dict[str, Any]
    ) -> JSONCompletionResult:
        started = time.monotonic()
        try:
            response = await self._client.post(
                f"{self._base_url}/models/{request.model}:generateContent",
                json=body,
                headers={"x-goog-api-key": self._api_key},
                timeout=request.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise classify_transport(exc, "gemini") from exc
        error = classify_status(response, "gemini")
        if error is not None:
            raise error
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMRetryableError(f"gemini returned non-JSON: {exc}") from exc
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise LLMPermanentError(f"gemini blocked the prompt: {block}")
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMRetryableError("gemini returned no candidates")
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish in _BLOCKED_FINISH:
            raise LLMPermanentError(f"gemini stopped with finishReason={finish}")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise LLMRetryableError("gemini returned empty content in JSON mode")
        usage = data.get("usageMetadata") or {}
        return JSONCompletionResult(
            provider=self.name,
            model=str(data.get("modelVersion") or request.model),
            text=text,
            usage=LLMUsage(
                input_tokens=int(usage.get("promptTokenCount", 0)),
                output_tokens=int(usage.get("candidatesTokenCount", 0))
                + int(usage.get("thoughtsTokenCount", 0)),
                cached_input_tokens=int(usage.get("cachedContentTokenCount", 0)),
            ),
            finish_reason=finish,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
