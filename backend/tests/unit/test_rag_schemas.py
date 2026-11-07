from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from pareeksha.schemas.prompts import PromptVersionCreate, content_hash
from pareeksha.schemas.rag import (
    ChunkingConfig,
    RagConfig,
    RagExpectation,
    index_key,
    rag_label,
)

KB = uuid.UUID(int=1)


def _cfg(**over: Any) -> RagConfig:
    return RagConfig(**{"kb_id": KB, **over})


def _body(**over: Any) -> PromptVersionCreate:
    data: dict[str, Any] = {"system_prompt": "be nice", "provider": "openai", "model": "gpt-x"}
    return PromptVersionCreate(**{**data, **over})


def test_rag_config_defaults_and_label() -> None:
    cfg = _cfg(method="hybrid_rerank")
    assert cfg.mode == "retrieval" and cfg.top_k == 5 and cfg.candidate_k == 20
    assert rag_label(cfg) == "hybrid+rerank · recursive 800/100 · e5-large · k5"
    assert rag_label(_cfg(label="mine")) == "mine"


def test_overlap_must_be_at_most_half_size() -> None:
    ChunkingConfig(size=200, overlap=100)
    with pytest.raises(ValidationError):
        ChunkingConfig(size=200, overlap=101)


def test_hyde_requires_dense_method() -> None:
    with pytest.raises(ValidationError):
        _cfg(method="bm25", query_transform="hyde")
    assert _cfg(method="dense", query_transform="hyde").query_transform == "hyde"


def test_index_key_ignores_retrieval_params() -> None:
    base = _cfg()
    assert index_key(base) == index_key(_cfg(method="bm25", top_k=9))
    assert index_key(base) != index_key(_cfg(chunking={"size": 500}))


def test_prompt_version_hash_changes_with_rag_config() -> None:
    assert content_hash(_body()) != content_hash(_body(rag_config={"kb_id": str(KB)}))


def test_prompt_version_hash_unchanged_without_rag_config() -> None:
    # Pinned: the hash of a pre-RAG version must not move when rag_config is added to the model.
    assert content_hash(_body()) == content_hash(_body(rag_config=None))
    legacy = json.dumps(
        _body().model_dump(mode="json", exclude={"note", "rag_config"}),
        sort_keys=True,
        separators=(",", ":"),
    )
    assert content_hash(_body()) == hashlib.sha256(legacy.encode()).hexdigest()


def test_unanswerable_expectation_needs_no_span() -> None:
    assert RagExpectation(answerable=False).source_span is None
    with pytest.raises(ValidationError):
        RagExpectation()
