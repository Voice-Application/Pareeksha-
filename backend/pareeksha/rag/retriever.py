"""Retrieval for a prompt agent's turn: BM25 / dense / hybrid / rerank / MMR, query transforms,
small-to-big context. The index lives in a small in-process LRU (loaded from Postgres by
``simulation.store``); this module does no I/O of its own besides the embedder, reranker and chat.
"""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pareeksha.agent_llm.base import AgentLLMError, AgentMessage, ChatProvider
from pareeksha.rag.bm25 import BM25
from pareeksha.rag.chunking import tokenize
from pareeksha.rag.embeddings import Embedder, build_embedder
from pareeksha.rag.rerank import Reranker, build_reranker
from pareeksha.rag.search import dense_scores, mmr, rrf, top_k
from pareeksha.schemas.rag import RagConfig

_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n?(.*?)\n?```$", re.DOTALL)
INDEX_CACHE_SIZE = 8


@dataclass(slots=True)
class LoadedIndex:
    #: per chunk: id, document_id, filename, text, start_char, end_char, parent_start, parent_end
    chunks: list[dict[str, Any]]
    #: (n, dim) float32, rows normalised to unit length
    matrix: np.ndarray
    bm25: BM25
    #: document_id -> full text, for small-to-big
    docs: dict[str, str]


def build_loaded_index(chunks: Sequence[Mapping[str, Any]], docs: Mapping[str, str]) -> LoadedIndex:
    """``chunks`` carry an ``embedding`` (list of floats or None) beside the metadata."""
    meta = [{k: v for k, v in c.items() if k != "embedding"} for c in chunks]
    dim = next((len(c["embedding"]) for c in chunks if c.get("embedding")), 0)
    matrix = np.zeros((len(chunks), dim), dtype=np.float32)
    for i, c in enumerate(chunks):
        if c.get("embedding") and len(c["embedding"]) == dim:
            matrix[i] = c["embedding"]
    norm = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = (matrix / np.where(norm == 0, 1.0, norm)).astype(np.float32)
    return LoadedIndex(meta, matrix, BM25([tokenize(c["text"]) for c in meta]), dict(docs))


_CACHE: OrderedDict[Any, LoadedIndex] = OrderedDict()


async def get_or_load(index_id: Any, loader: Callable[[], Awaitable[LoadedIndex]]) -> LoadedIndex:
    """The cached index, else ``await loader()`` and keep it (LRU of 8, per process)."""
    hit = _CACHE.get(index_id)
    if hit is not None:
        _CACHE.move_to_end(index_id)
        return hit
    loaded = await loader()
    _CACHE[index_id] = loaded
    while len(_CACHE) > INDEX_CACHE_SIZE:
        _CACHE.popitem(last=False)
    return loaded


@dataclass(slots=True)
class RetrievalOutcome:
    results: list[dict[str, Any]]
    context: str
    queries: list[str]
    timings: dict[str, int] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)
    #: e.g. ``query_transform_failed``; the runner logs each as an event
    warnings: list[str] = field(default_factory=list)


def format_context(blocks: Sequence[tuple[str, str]]) -> str:
    """``(filename, text)`` pairs as ``[1] (source: f)\\ntext`` blocks."""
    return "\n\n".join(f"[{i}] (source: {f})\n{t}" for i, (f, t) in enumerate(blocks, start=1))


def parse_rewrites(text: str) -> list[str]:
    body = text.strip()
    m = _FENCE.match(body)
    if m:
        body = m.group(1)
    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError("not a list")
    return [s.strip() for s in data if isinstance(s, str) and s.strip()]


class Retriever:
    def __init__(
        self,
        cfg: RagConfig,
        index: LoadedIndex,
        embedder: Embedder,
        reranker: Reranker | None = None,
        *,
        model: str = "",
        temperature: float = 0.2,
    ) -> None:
        self.cfg, self.index, self.embedder, self.reranker = cfg, index, embedder, reranker
        self.model, self.temperature = model, temperature

    async def _chat(self, chat: ChatProvider, system: str, user: str, usage: dict[str, int]) -> str:
        reply = await chat.chat(
            [AgentMessage("system", system), AgentMessage("user", user)],
            [],
            model=self.model,
            temperature=self.temperature,
        )
        usage["transform_input_tokens"] = (
            usage.get("transform_input_tokens", 0) + reply.input_tokens
        )
        usage["transform_output_tokens"] = (
            usage.get("transform_output_tokens", 0) + reply.output_tokens
        )
        return reply.text

    async def retrieve(self, query: str, *, chat: ChatProvider | None) -> RetrievalOutcome:
        cfg, idx = self.cfg, self.index
        t0 = time.monotonic()
        timings: dict[str, int] = {}
        usage: dict[str, int] = {}
        warnings: list[str] = []
        queries = [query]
        dense_texts = [query]
        t = time.monotonic()
        if cfg.query_transform != "none" and chat is not None:
            try:
                if cfg.query_transform == "multi_query":
                    raw = await self._chat(
                        chat,
                        "Rewrite the user's question as 3 different search queries. "
                        "Reply with only a JSON list of 3 strings.",
                        query,
                        usage,
                    )
                    queries += parse_rewrites(raw)[:3]
                    dense_texts = list(queries)
                else:
                    hyp = await self._chat(
                        chat,
                        "Write a short passage (2-4 sentences) that would answer the question. "
                        "Reply with only the passage.",
                        query,
                        usage,
                    )
                    if hyp.strip():
                        dense_texts = [hyp.strip()]
            except (AgentLLMError, ValueError):
                warnings.append("query_transform_failed")
                queries, dense_texts = [query], [query]
        timings["transform_ms"] = int((time.monotonic() - t) * 1000)

        vecs: list[np.ndarray] = []
        if cfg.method != "bm25":
            t = time.monotonic()
            emb = await self.embedder.embed(dense_texts, kind="query")
            timings["embed_ms"] = int((time.monotonic() - t) * 1000)
            usage["embed_tokens"] = emb.input_tokens
            vecs = [np.asarray(v, dtype=np.float32) for v in emb.vectors]

        def bm25_rank(q: str) -> list[int]:
            return [i for i, _ in top_k(idx.bm25.scores(tokenize(q)), cfg.candidate_k)]

        def dense_rank(v: np.ndarray) -> list[int]:
            return [i for i, _ in top_k(dense_scores(v, idx.matrix), cfg.candidate_k)]

        rankings: list[list[int]] = []
        for n, q in enumerate(queries):
            v = vecs[n if len(vecs) == len(queries) else 0] if vecs else None
            if cfg.method == "bm25":
                rankings.append(bm25_rank(q))
            elif cfg.method in ("dense", "mmr") and v is not None:
                rankings.append(dense_rank(v))
            elif v is not None:
                rankings.append(
                    [i for i, _ in rrf([bm25_rank(q), dense_rank(v)], cfg.rrf_k)][: cfg.candidate_k]
                )
        if len(rankings) > 1:
            cands = [i for i, _ in rrf(rankings, cfg.rrf_k)][: cfg.candidate_k]
        else:
            cands = rankings[0] if rankings else []

        scores: dict[int, float] = {}
        if cfg.method == "hybrid_rerank" and self.reranker is not None and cands:
            rr, ms = await self.reranker.rerank(query, [idx.chunks[i]["text"] for i in cands])
            timings["rerank_ms"] = ms
            picked = top_k(rr, cfg.top_k)
            chosen = [cands[p] for p, _ in picked]
            scores = {cands[p]: s for p, s in picked}
        elif cfg.method == "mmr" and vecs and cands:
            chosen = mmr(vecs[0], idx.matrix, cands, cfg.top_k, cfg.mmr_lambda)
        else:
            chosen = cands[: cfg.top_k]
        if not scores:
            if cfg.method == "bm25":
                raw_scores = idx.bm25.scores(tokenize(query))
            elif vecs:
                raw_scores = dense_scores(vecs[0], idx.matrix).tolist()
            else:
                raw_scores = []
            scores = {i: float(raw_scores[i]) for i in chosen if i < len(raw_scores)}

        results = []
        for rank, i in enumerate(chosen, start=1):
            c = idx.chunks[i]
            results.append(
                {
                    "rank": rank,
                    "chunk_id": str(c["id"]),
                    "document_id": str(c["document_id"]),
                    "filename": c["filename"],
                    "start_char": c["start_char"],
                    "end_char": c["end_char"],
                    "score": scores.get(i, 0.0),
                    "text": c["text"],
                }
            )
        blocks: list[tuple[str, str]] = []
        seen: set[tuple[str, int, int]] = set()
        for i in chosen:
            c = idx.chunks[i]
            text = c["text"]
            if cfg.small_to_big:
                key = (str(c["document_id"]), c["parent_start"], c["parent_end"])
                if key in seen:
                    continue
                seen.add(key)
                doc = idx.docs.get(str(c["document_id"]))
                if doc is not None:
                    text = doc[c["parent_start"] : c["parent_end"]]
            blocks.append((c["filename"], text))
        timings["total_ms"] = int((time.monotonic() - t0) * 1000)
        return RetrievalOutcome(results, format_context(blocks), queries, timings, usage, warnings)


def build_retriever(
    rag: Mapping[str, Any], secrets: Mapping[str, str], *, model: str, temperature: float
) -> Retriever:
    """From ``AgentTarget.adapter_config["rag"]`` (config, loaded ``index``) and KB secrets."""
    cfg = RagConfig.model_validate(rag["config"])
    embedder = build_embedder(cfg.embedding, api_key=secrets.get("embedding_api_key"))
    reranker = (
        build_reranker(
            cfg.reranker_provider, cfg.reranker_model, api_key=secrets.get("reranker_api_key")
        )
        if cfg.method == "hybrid_rerank"
        else None
    )
    return Retriever(cfg, rag["index"], embedder, reranker, model=model, temperature=temperature)
