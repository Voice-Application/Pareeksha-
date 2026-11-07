from __future__ import annotations

import pytest

from pareeksha.rag.indexing import _api_key
from pareeksha.schemas.rag import (
    ChunkingConfig,
    EmbeddingConfig,
    RagConfig,
    index_key,
    index_key_for,
)


def test_index_key_for_matches_index_key() -> None:
    cfg = RagConfig(kb_id="11111111-1111-4111-8111-111111111111")  # type: ignore[arg-type]
    assert index_key(cfg) == index_key_for(cfg.chunking, cfg.embedding)
    other = index_key_for(ChunkingConfig(size=200), EmbeddingConfig())
    assert other != index_key(cfg)


def test_no_secrets_means_no_key() -> None:
    assert _api_key(None) is None
    assert _api_key(b"") is None


def test_secrets_need_a_server_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValueError, match="SECRET_KEY"):
        _api_key(b"token")
