"""RAG configuration shared by prompt versions, runs and scenarios (plans/2026-11-07-rag-lab.md)."""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from pareeksha.schemas.common import RequestModel

EmbeddingProviderName = Literal[
    "local",
    "gemini",
    "openai",
    "openai_compatible",
    "azure_openai",
    "cohere",
    "voyage",
    "jina",
    "mistral",
    "bedrock",
    "ollama",
]
RerankerProviderName = Literal["local", "cohere", "jina", "voyage"]

DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3-int8"


class ChunkingConfig(RequestModel):
    strategy: Literal["fixed", "recursive", "sentence_window"] = "recursive"
    size: int = Field(default=800, ge=100, le=8000, description="characters")
    overlap: int = Field(default=100, ge=0)
    window: int = Field(default=2, ge=1, le=5, description="sentence_window only")

    @model_validator(mode="after")
    def _overlap_at_most_half(self) -> ChunkingConfig:
        if self.overlap > self.size // 2:
            raise ValueError("overlap must be at most half of size")
        return self


class EmbeddingConfig(RequestModel):
    provider: EmbeddingProviderName = "local"
    model: str = DEFAULT_EMBEDDING_MODEL
    base_url: str | None = None
    dimensions: int | None = None


class RagConfig(RequestModel):
    mode: Literal["off", "retrieval", "full_context"] = "retrieval"
    kb_id: UUID
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    method: Literal["bm25", "dense", "hybrid", "hybrid_rerank", "mmr"] = "hybrid"
    top_k: int = Field(default=5, ge=1, le=20)
    candidate_k: int = Field(default=20, le=100)
    rrf_k: int = 60
    mmr_lambda: float = Field(default=0.5, ge=0, le=1)
    reranker_provider: RerankerProviderName = "local"
    reranker_model: str = DEFAULT_RERANKER_MODEL
    query_transform: Literal["none", "multi_query", "hyde"] = "none"
    small_to_big: bool = False
    context_char_limit: int = 400_000
    label: str = Field(default="", max_length=60)

    @model_validator(mode="after")
    def _check(self) -> RagConfig:
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be at least top_k")
        if self.query_transform == "hyde" and self.method == "bm25":
            raise ValueError("hyde requires a method that uses dense retrieval")
        return self


class RagExpectation(RequestModel):
    source_document_id: UUID | None = None
    source_span: tuple[int, int] | None = None
    reference_answer: str = ""
    answerable: bool = True

    @model_validator(mode="after")
    def _answerable_needs_source(self) -> RagExpectation:
        if self.answerable and (self.source_document_id is None or self.source_span is None):
            raise ValueError("answerable expectations need source_document_id and source_span")
        return self


def rag_label(cfg: RagConfig) -> str:
    if cfg.label:
        return cfg.label
    method = cfg.method.replace("_rerank", "+rerank")
    model = cfg.embedding.model.rsplit("/", 1)[-1].removeprefix("multilingual-")
    c = cfg.chunking
    return f"{method} · {c.strategy} {c.size}/{c.overlap} · {model} · k{cfg.top_k}"


def index_key(cfg: RagConfig) -> str:
    e = cfg.embedding
    payload = json.dumps(
        [cfg.chunking.model_dump(mode="json"), e.provider, e.model, e.dimensions],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
