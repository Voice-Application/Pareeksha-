"""Which local (fastembed) model names may be loaded: only the ones fastembed itself lists, so a
request can never make a worker download or open an arbitrary model id."""

from __future__ import annotations

from functools import cache

from pareeksha.schemas.rag import RagConfig


class UnsupportedModelError(ValueError):
    def __init__(self, kind: str, model: str) -> None:
        super().__init__(f"unsupported local {kind} model {model!r}")
        self.kind, self.model = kind, model


@cache
def supported_embedding_models() -> frozenset[str]:
    from fastembed import TextEmbedding

    return frozenset(m["model"] for m in TextEmbedding.list_supported_models())


@cache
def supported_reranker_models() -> frozenset[str]:
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return frozenset(m["model"] for m in TextCrossEncoder.list_supported_models())


def require_supported_embedding(provider: str, model: str) -> None:
    if provider == "local" and model not in supported_embedding_models():
        raise UnsupportedModelError("embedding", model)


def require_supported_reranker(provider: str, model: str) -> None:
    if provider == "local" and model not in supported_reranker_models():
        raise UnsupportedModelError("reranker", model)


def require_supported_models(cfg: RagConfig) -> None:
    """The models a run of ``cfg`` would load (a full-context run loads none)."""
    if cfg.mode == "retrieval":
        require_supported_embedding(cfg.embedding.provider, cfg.embedding.model)
        if cfg.method == "hybrid_rerank":
            require_supported_reranker(cfg.reranker_provider, cfg.reranker_model)
