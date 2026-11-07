"""Local model names: only what fastembed itself lists."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from pareeksha.rag import local_models
from pareeksha.rag.local_models import (
    UnsupportedModelError,
    require_supported_embedding,
    require_supported_models,
    require_supported_reranker,
)
from pareeksha.schemas.rag import RagConfig


@pytest.fixture
def fake_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        local_models, "supported_embedding_models", lambda: frozenset({"org/emb-ok"})
    )
    monkeypatch.setattr(local_models, "supported_reranker_models", lambda: frozenset({"org/rr-ok"}))


def cfg(**kw: Any) -> RagConfig:
    return RagConfig.model_validate({"kb_id": uuid.uuid4(), **kw})


@pytest.mark.usefixtures("fake_lists")
def test_listed_and_unlisted_local_models() -> None:
    require_supported_embedding("local", "org/emb-ok")
    require_supported_reranker("local", "org/rr-ok")
    with pytest.raises(UnsupportedModelError, match="evil/emb"):
        require_supported_embedding("local", "evil/emb")
    with pytest.raises(UnsupportedModelError, match="evil/rr"):
        require_supported_reranker("local", "evil/rr")


@pytest.mark.usefixtures("fake_lists")
def test_hosted_models_are_not_checked() -> None:
    require_supported_embedding("openai", "text-embedding-3-small")
    require_supported_reranker("cohere", "rerank-v3.5")


@pytest.mark.usefixtures("fake_lists")
def test_rag_config_checks_only_the_models_it_loads() -> None:
    bad_emb = {"embedding": {"provider": "local", "model": "evil/emb"}}
    with pytest.raises(UnsupportedModelError):
        require_supported_models(cfg(method="bm25", **bad_emb))
    require_supported_models(cfg(mode="full_context", **bad_emb))  # loads no model
    require_supported_models(cfg(mode="off", **bad_emb))
    ok_emb = {"embedding": {"provider": "local", "model": "org/emb-ok"}}
    require_supported_models(cfg(method="hybrid", **ok_emb))  # reranker unused
    with pytest.raises(UnsupportedModelError, match="reranker"):
        require_supported_models(cfg(method="hybrid_rerank", reranker_model="evil/rr", **ok_emb))
    require_supported_models(cfg(method="hybrid_rerank", reranker_model="org/rr-ok", **ok_emb))


def test_lists_come_from_fastembed_and_are_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    import fastembed
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    calls: list[str] = []

    def emb() -> list[dict[str, str]]:
        calls.append("emb")
        return [{"model": "a/b"}]

    monkeypatch.setattr(fastembed.TextEmbedding, "list_supported_models", staticmethod(emb))
    monkeypatch.setattr(
        TextCrossEncoder, "list_supported_models", staticmethod(lambda: [{"model": "c/d"}])
    )
    local_models.supported_embedding_models.cache_clear()
    local_models.supported_reranker_models.cache_clear()
    try:
        assert local_models.supported_embedding_models() == {"a/b"}
        assert local_models.supported_embedding_models() == {"a/b"}
        assert calls == ["emb"]  # cached
        assert local_models.supported_reranker_models() == {"c/d"}
    finally:  # do not leave the fake lists cached for other tests
        local_models.supported_embedding_models.cache_clear()
        local_models.supported_reranker_models.cache_clear()


def test_the_default_models_are_supported() -> None:
    """The real fastembed lists contain the plan's defaults (no network needed to list them)."""
    from pareeksha.schemas.rag import DEFAULT_EMBEDDING_MODEL, DEFAULT_RERANKER_MODEL

    local_models.supported_embedding_models.cache_clear()
    local_models.supported_reranker_models.cache_clear()
    require_supported_embedding("local", DEFAULT_EMBEDDING_MODEL)
    require_supported_reranker("local", DEFAULT_RERANKER_MODEL)
