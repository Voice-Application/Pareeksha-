"""Provider-independent JSON client: schema validation, one repair retry, usage logging.

Built on :class:`~pareeksha.llm.base.LLMProvider`. Every provider call (including the repair
retry) produces a :class:`UsageRecord` that goes to the ``usage_sink`` (``api_usage`` rows, the
credit ledger, logs).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from pareeksha.llm.base import (
    ChatMessage,
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMPermanentError,
    LLMProvider,
    LLMProviderName,
    LLMPurpose,
    LLMUsage,
)
from pareeksha.llm.config import LLMSettings

log = logging.getLogger("pareeksha.llm")

M = TypeVar("M", bound=BaseModel)

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


class UsageRecord(BaseModel):
    """One provider call, shaped for ``api_usage`` (operation ``llm_<purpose>``)."""

    provider: LLMProviderName
    model: str
    purpose: LLMPurpose
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int = 0
    est_cost: float | None = None
    latency_ms: int = 0
    prompt_hash: str | None = None
    repair: bool = False
    cache_hit: bool = False


UsageSink = Callable[[UsageRecord], Awaitable[None] | None]


class JSONCache(Protocol):
    """Optional response cache; lets a seeded caller utterance be reproduced exactly."""

    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str) -> None: ...


class InMemoryJSONCache:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value


class FileJSONCache:
    """One JSON file per key under ``directory``: seeded outputs survive process restarts."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        directory.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> str | None:
        path = self._dir / f"{key}.json"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def set(self, key: str, value: str) -> None:
        (self._dir / f"{key}.json").write_text(value, encoding="utf-8")


class JSONGenerationError(LLMPermanentError):
    """The model never produced valid output (after the repair retry)."""

    def __init__(self, message: str, *, raw_text: str = "") -> None:
        super().__init__(message)
        self.raw_text = raw_text


class GenerationResult(BaseModel, Generic[M]):
    model_config = {"arbitrary_types_allowed": True}

    parsed: M
    raw_text: str
    provider: LLMProviderName
    model: str
    usage: LLMUsage
    est_cost: float | None = None
    prompt_hash: str | None = None
    repaired: bool = False
    cache_hit: bool = False
    latency_ms: int = 0


def parse_json_text(text: str) -> Any:
    """``json.loads`` that tolerates a markdown fence around the document."""
    stripped = text.strip()
    match = _FENCE.match(stripped)
    if match:
        stripped = match.group(1)
    return json.loads(stripped)


class LLMClient:
    def __init__(
        self,
        provider: LLMProvider,
        settings: LLMSettings,
        *,
        usage_sink: UsageSink | None = None,
        cache: JSONCache | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self._sink = usage_sink
        self._cache = cache

    async def aclose(self) -> None:
        await self.provider.aclose()

    async def generate_json(
        self,
        *,
        purpose: LLMPurpose,
        messages: list[ChatMessage],
        schema: type[M],
        prompt_hash: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        thinking: bool = False,
        timeout_s: float = 60.0,
        semantic_check: Callable[[M], str | None] | None = None,
        cache_salt: str | None = None,
    ) -> GenerationResult[M]:
        """Generate one ``schema`` object.

        ``semantic_check`` returns an error string for output that parses but is wrong (for example
        evidence turn indices that do not exist); it triggers the same single repair retry.
        ``cache_salt`` enables the response cache for this call (e.g. the call seed).
        """
        request = JSONCompletionRequest(
            purpose=purpose,
            model=model or self.settings.model_for(purpose),
            messages=messages,
            temperature=(
                temperature if temperature is not None else self.settings.temperature_for(purpose)
            ),
            json_schema=schema.model_json_schema(),
            max_output_tokens=max_output_tokens,
            thinking=thinking,
            timeout_s=timeout_s,
        )
        cache_key = self._cache_key(request, cache_salt) if cache_salt is not None else None
        if cache_key is not None and self._cache is not None:
            hit = self._cache.get(cache_key)
            if hit is not None:
                try:
                    cached = schema.model_validate(parse_json_text(hit))
                except (ValueError, ValidationError):
                    pass  # bad cache entry: fall through to a real call
                else:
                    return await self._cached_result(request, cached, hit, prompt_hash)

        first = await self._call(request, prompt_hash, repair=False)
        parsed, error = self._validate(first.text, schema, semantic_check)
        if parsed is not None:
            return self._finish(request, first, parsed, prompt_hash, False, cache_key)

        repair_request = request.model_copy(
            update={
                "messages": [
                    *request.messages,
                    ChatMessage(role="assistant", content=first.text),
                    ChatMessage(
                        role="user",
                        content=(
                            f"Your previous json was rejected: {error}\n"
                            "Return the corrected json object only, following the schema."
                        ),
                    ),
                ]
            }
        )
        second = await self._call(repair_request, prompt_hash, repair=True)
        parsed, error = self._validate(second.text, schema, semantic_check)
        if parsed is None:
            raise JSONGenerationError(
                f"model output still invalid after one repair retry: {error}",
                raw_text=second.text,
            )
        merged = second.model_copy(
            update={
                "usage": LLMUsage(
                    input_tokens=first.usage.input_tokens + second.usage.input_tokens,
                    output_tokens=first.usage.output_tokens + second.usage.output_tokens,
                    cached_input_tokens=first.usage.cached_input_tokens
                    + second.usage.cached_input_tokens,
                ),
                "latency_ms": first.latency_ms + second.latency_ms,
            }
        )
        return self._finish(request, merged, parsed, prompt_hash, True, cache_key)

    # -- internals ------------------------------------------------------------------------

    @staticmethod
    def _validate(
        text: str, schema: type[M], semantic_check: Callable[[M], str | None] | None
    ) -> tuple[M | None, str]:
        try:
            parsed = schema.model_validate(parse_json_text(text))
        except json.JSONDecodeError as exc:
            return None, f"not valid JSON ({exc})"
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:8]
            )
            return None, f"schema violations: {problems}"
        if semantic_check is not None:
            problem = semantic_check(parsed)
            if problem:
                return None, problem
        return parsed, ""

    @staticmethod
    def _cache_key(request: JSONCompletionRequest, salt: str) -> str:
        blob = request.model_dump_json() + "\x00" + salt
        return hashlib.sha256(blob.encode()).hexdigest()

    async def _call(
        self, request: JSONCompletionRequest, prompt_hash: str | None, *, repair: bool
    ) -> JSONCompletionResult:
        result = await self.provider.complete_json(request)
        await self._log(
            UsageRecord(
                provider=result.provider,
                model=result.model,
                purpose=request.purpose,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                cached_input_tokens=result.usage.cached_input_tokens,
                est_cost=self.settings.estimate_cost(result.usage),
                latency_ms=result.latency_ms,
                prompt_hash=prompt_hash,
                repair=repair,
            )
        )
        return result

    async def _cached_result(
        self, request: JSONCompletionRequest, parsed: M, raw: str, prompt_hash: str | None
    ) -> GenerationResult[M]:
        await self._log(
            UsageRecord(
                provider=self.provider.name,
                model=request.model,
                purpose=request.purpose,
                input_tokens=0,
                output_tokens=0,
                est_cost=0.0,
                prompt_hash=prompt_hash,
                cache_hit=True,
            )
        )
        return GenerationResult[M](
            parsed=parsed,
            raw_text=raw,
            provider=self.provider.name,
            model=request.model,
            usage=LLMUsage(input_tokens=0, output_tokens=0),
            est_cost=0.0,
            prompt_hash=prompt_hash,
            cache_hit=True,
        )

    def _finish(
        self,
        request: JSONCompletionRequest,
        result: JSONCompletionResult,
        parsed: M,
        prompt_hash: str | None,
        repaired: bool,
        cache_key: str | None,
    ) -> GenerationResult[M]:
        if cache_key is not None and self._cache is not None:
            self._cache.set(cache_key, result.text)
        return GenerationResult[M](
            parsed=parsed,
            raw_text=result.text,
            provider=result.provider,
            model=result.model,
            usage=result.usage,
            est_cost=self.settings.estimate_cost(result.usage),
            prompt_hash=prompt_hash,
            repaired=repaired,
            latency_ms=result.latency_ms,
        )

    async def _log(self, record: UsageRecord) -> None:
        log.info(
            "llm_call provider=%s model=%s purpose=%s in=%d out=%d cached_in=%d cost=%s "
            "latency_ms=%d repair=%s cache_hit=%s",
            record.provider.value,
            record.model,
            record.purpose.value,
            record.input_tokens,
            record.output_tokens,
            record.cached_input_tokens,
            record.est_cost,
            record.latency_ms,
            record.repair,
            record.cache_hit,
        )
        if self._sink is not None:
            outcome = self._sink(record)
            if inspect.isawaitable(outcome):
                await outcome
