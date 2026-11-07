"""RAG configuration shared by prompt versions, runs and scenarios (plans/2026-11-07-rag-lab.md)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


def index_key_for(chunking: ChunkingConfig, e: EmbeddingConfig) -> str:
    payload = json.dumps(
        [chunking.model_dump(mode="json"), e.provider, e.model, e.dimensions],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def index_key(cfg: RagConfig) -> str:
    return index_key_for(cfg.chunking, cfg.embedding)


class KbSecrets(RequestModel):
    """Write-only provider keys for a knowledge base."""

    embedding_api_key: str | None = None
    reranker_api_key: str | None = None


class KnowledgeBaseCreate(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    local_only: bool = False
    #: Write-only; stored encrypted, never returned.
    secrets: KbSecrets | None = Field(default=None, exclude=True)


class KnowledgeBaseUpdate(RequestModel):
    """PATCH: only provided fields change."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    local_only: bool | None = None
    #: Write-only; `{}` clears the stored secrets.
    secrets: KbSecrets | None = Field(default=None, exclude=True)


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    local_only: bool
    has_secrets: bool = False
    created_at: datetime
    updated_at: datetime


class KbDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    mime: str
    char_count: int
    sha256: str
    created_at: datetime


class KbDocumentDetail(KbDocumentOut):
    text: str


class KbIndexCreate(RequestModel):
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)


class KbIndexOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    index_key: str
    status: str
    chunking: dict[str, Any]
    embedding: dict[str, Any]
    chunk_count: int
    stats: dict[str, Any]
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class KbChunkOut(BaseModel):
    """A chunk as the browser shows it: text and offsets, never the vector."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    ordinal: int
    text: str
    start_char: int
    end_char: int
    parent_start: int
    parent_end: int
