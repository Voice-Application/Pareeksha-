"""Embedding providers: local fastembed, or hosted over the shared SSRF-safe ``post_json``."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol
from urllib.parse import quote

import httpx

from pareeksha.agent_llm.base import AgentLLMError, post_json
from pareeksha.agent_llm.url_guard import ollama_base_url
from pareeksha.schemas.rag import EmbeddingConfig

BATCH_SIZE = 64
Kind = Literal["query", "document"]

_MODELS: dict[str, Any] = {}
_LOCK = threading.Lock()

#: Public endpoints; Ollama's comes from ``ollama_base_url()`` (``OLLAMA_BASE_URL``).
_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "jina": "https://api.jina.ai/v1",
}
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True, slots=True)
class EmbedResult:
    vectors: list[list[float]]
    input_tokens: int
    latency_ms: int


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str], *, kind: Kind) -> EmbedResult: ...


def _model(name: str) -> Any:
    with _LOCK:
        if name not in _MODELS:
            from fastembed import TextEmbedding

            _MODELS[name] = TextEmbedding(
                name, cache_dir=os.environ.get("FASTEMBED_CACHE_PATH", "/data/models")
            )
        return _MODELS[name]


def _estimate_tokens(texts: Sequence[str]) -> int:
    return sum(len(t) for t in texts) // 4


class LocalEmbedder:
    def __init__(self, model: str):
        self._model = model

    async def embed(self, texts: Sequence[str], *, kind: Kind) -> EmbedResult:
        if not texts:
            return EmbedResult([], 0, 0)
        # Load (and on first use download) the model outside the timed span: latency_ms is the
        # inference time only, so a cold worker does not skew retrieval-latency metrics.
        m = await asyncio.to_thread(_model, self._model)
        fn = m.query_embed if kind == "query" else m.passage_embed

        def run() -> list[list[float]]:
            return [[float(x) for x in v] for v in fn(list(texts))]

        start = time.monotonic()
        vectors = await asyncio.to_thread(run)
        return EmbedResult(vectors, _estimate_tokens(texts), int((time.monotonic() - start) * 1000))


def _bad() -> AgentLLMError:
    return AgentLLMError("embedding provider returned an unexpected response")


class HostedEmbedder:
    def __init__(
        self, cfg: EmbeddingConfig, api_key: str | None, http: httpx.AsyncClient | None = None
    ):
        self._cfg = cfg
        self._key = api_key
        self._http = http
        p = cfg.provider
        if p in ("openai_compatible", "azure_openai", "bedrock") and not cfg.base_url:
            raise ValueError(f"{p} embeddings require base_url")
        default = ollama_base_url() if p == "ollama" else _BASE_URLS.get(p)
        self._base = (cfg.base_url or default or "").rstrip("/")

    async def _post(
        self, url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> tuple[dict[str, Any], int]:
        return await post_json(self._http, url, headers, body, timeout_s=60.0, api_key=self._key)

    async def embed(self, texts: Sequence[str], *, kind: Kind) -> EmbedResult:
        vectors: list[list[float]] = []
        tokens = 0
        ms = 0
        for i in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[i : i + BATCH_SIZE])
            try:
                vecs, tok, took = await self._batch(batch, kind)
            except (KeyError, TypeError, ValueError, IndexError) as exc:
                raise _bad() from exc
            if len(vecs) != len(batch):
                raise _bad()
            vectors += vecs
            tokens += tok
            ms += took
        return EmbedResult(vectors, tokens, ms)

    async def _batch(self, batch: list[str], kind: Kind) -> tuple[list[list[float]], int, int]:
        cfg, key, p = self._cfg, self._key, self._cfg.provider
        bearer = {"Authorization": f"Bearer {key}"} if key else {}
        if p == "cohere":
            body: dict[str, Any] = {
                "model": cfg.model,
                "texts": batch,
                "input_type": "search_query" if kind == "query" else "search_document",
                "embedding_types": ["float"],
            }
            if cfg.dimensions:
                body["output_dimension"] = cfg.dimensions
            data, ms = await self._post("https://api.cohere.com/v2/embed", bearer, body)
            units = (data.get("meta") or {}).get("billed_units") or {}
            tok = int(units.get("input_tokens") or _estimate_tokens(batch))
            return data["embeddings"]["float"], tok, ms
        if p == "gemini":
            # EmbedContentRequest = {model, content, embedContentConfig}; taskType and
            # outputDimensionality live in the config (ai.google.dev/api/embeddings, 2026-11)
            task = "RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT"
            config: dict[str, Any] = {"taskType": task}
            if cfg.dimensions:
                config["outputDimensionality"] = cfg.dimensions
            reqs = [
                {
                    "model": f"models/{cfg.model}",
                    "content": {"parts": [{"text": t}]},
                    "embedContentConfig": config,
                }
                for t in batch
            ]
            url = f"{self._base or _GEMINI_BASE}/models/{cfg.model}:batchEmbedContents"
            data, ms = await self._post(url, {"x-goog-api-key": key or ""}, {"requests": reqs})
            usage = data.get("usageMetadata") or {}
            tok = int(usage.get("promptTokenCount") or _estimate_tokens(batch))
            return [e["values"] for e in data["embeddings"]], tok, ms
        if p == "bedrock":
            return await self._bedrock(batch, kind, bearer)
        # OpenAI wire (openai, mistral, jina, ollama, openai_compatible), plus Voyage and Azure.
        body = {"model": cfg.model, "input": batch}
        url = f"{self._base}/embeddings"
        headers = bearer
        if p == "voyage":
            url = "https://api.voyageai.com/v1/embeddings"
            body["input_type"] = kind
        elif p == "azure_openai":
            url = f"{self._base}/embeddings?api-version=2024-10-21"
            headers = {"api-key": key or ""}
        if cfg.dimensions:
            body["output_dimension" if p == "voyage" else "dimensions"] = cfg.dimensions
        data, ms = await self._post(url, headers, body)
        usage = data.get("usage") or {}
        tok = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
        rows = sorted(data["data"], key=lambda r: r.get("index", 0))
        return [r["embedding"] for r in rows], tok or _estimate_tokens(batch), ms

    async def _bedrock(
        self, batch: list[str], kind: Kind, headers: dict[str, str]
    ) -> tuple[list[list[float]], int, int]:
        url = f"{self._base}/model/{quote(self._cfg.model, safe='')}/invoke"
        if self._cfg.model.startswith("cohere."):
            body = {
                "texts": batch,
                "input_type": "search_query" if kind == "query" else "search_document",
            }
            data, ms = await self._post(url, headers, body)
            return data["embeddings"], _estimate_tokens(batch), ms
        vecs: list[list[float]] = []
        tok = ms = 0
        for t in batch:  # Titan embeds one text per call
            data, took = await self._post(url, headers, {"inputText": t})
            vecs.append(data["embedding"])
            tok += int(data.get("inputTextTokenCount") or 0)
            ms += took
        return vecs, tok, ms


def build_embedder(
    cfg: EmbeddingConfig, *, api_key: str | None, http: httpx.AsyncClient | None = None
) -> Embedder:
    if cfg.provider == "local":
        return LocalEmbedder(cfg.model)
    return HostedEmbedder(cfg, api_key, http)
