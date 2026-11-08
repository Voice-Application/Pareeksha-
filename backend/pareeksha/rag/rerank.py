"""Rerankers: local fastembed cross-encoder, or hosted Cohere / Jina / Voyage."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Sequence
from typing import Any, Protocol

import httpx

from pareeksha.agent_llm.base import AgentLLMError, post_json

_ENCODERS: dict[str, Any] = {}
_LOCK = threading.Lock()

_URLS = {
    "cohere": "https://api.cohere.com/v2/rerank",
    "jina": "https://api.jina.ai/v1/rerank",
    "voyage": "https://api.voyageai.com/v1/rerank",
}


class Reranker(Protocol):
    async def rerank(self, query: str, docs: Sequence[str]) -> tuple[list[float], int]: ...


def _encoder(model: str) -> Any:
    with _LOCK:
        if model not in _ENCODERS:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            _ENCODERS[model] = TextCrossEncoder(
                model, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH", "/data/models")
            )
        return _ENCODERS[model]


class LocalReranker:
    def __init__(self, model: str):
        self._model = model

    async def rerank(self, query: str, docs: Sequence[str]) -> tuple[list[float], int]:
        encoder = await asyncio.to_thread(_encoder, self._model)  # load outside the timed span
        start = time.monotonic()
        scores = await asyncio.to_thread(
            lambda: [float(s) for s in encoder.rerank(query, list(docs))]
        )
        return scores, int((time.monotonic() - start) * 1000)


class HostedReranker:
    def __init__(
        self, provider: str, model: str, api_key: str | None, http: httpx.AsyncClient | None
    ):
        self._provider = provider
        self._model = model
        self._key = api_key
        self._http = http

    async def rerank(self, query: str, docs: Sequence[str]) -> tuple[list[float], int]:
        if not docs:
            return [], 0
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        body: dict[str, Any] = {"model": self._model, "query": query, "documents": list(docs)}
        # ask for every document back: a provider default below len(docs) would drop scores
        body["top_k" if self._provider == "voyage" else "top_n"] = len(docs)
        data, ms = await post_json(
            self._http, _URLS[self._provider], headers, body, timeout_s=60.0, api_key=self._key
        )
        # Cohere/Jina return "results", Voyage "data"; each row has index + relevance_score.
        rows = data.get("data") if self._provider == "voyage" else data.get("results")
        scores: list[float | None] = [None] * len(docs)
        try:
            for r in rows or []:
                scores[int(r["index"])] = float(r["relevance_score"])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise AgentLLMError("reranker returned an unexpected response") from exc
        if any(s is None for s in scores):
            raise AgentLLMError("reranker returned scores for only some documents")
        return [float(s) for s in scores if s is not None], ms


def build_reranker(
    provider: str, model: str, *, api_key: str | None, http: httpx.AsyncClient | None = None
) -> Reranker:
    if provider == "local":
        return LocalReranker(model)
    if provider in _URLS:
        return HostedReranker(provider, model, api_key, http)
    raise ValueError(f"unknown reranker provider {provider!r}")
