from __future__ import annotations

import socket

import pytest

from pareeksha.agent_llm.url_guard import ALLOW_PRIVATE_ENV
from pareeksha.rag.guard import (
    LocalOnlyError,
    is_local_endpoint,
    platform_llm_may_see_kb,
    require_local_agent,
    require_local_embedding,
    require_local_reranker,
)
from pareeksha.schemas.rag import EmbeddingConfig


def _resolve(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))],
    )


def test_ollama_and_local_are_local() -> None:
    assert is_local_endpoint("ollama", None)
    assert is_local_endpoint("local", None)


@pytest.mark.parametrize("p", ["openai", "gemini", "deepseek", "cohere", "anthropic"])
def test_hosted_names_never_local(p: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOW_PRIVATE_ENV, "1")
    _resolve(monkeypatch, "127.0.0.1")
    assert not is_local_endpoint(p, "http://127.0.0.1:1234/v1")


def test_openai_compatible_needs_opt_in_and_private_host(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "http://llm.internal:8000/v1"
    _resolve(monkeypatch, "10.0.0.5")
    monkeypatch.delenv(ALLOW_PRIVATE_ENV, raising=False)
    assert not is_local_endpoint("openai_compatible", url)  # no opt-in
    monkeypatch.setenv(ALLOW_PRIVATE_ENV, "1")
    assert is_local_endpoint("openai_compatible", url)
    _resolve(monkeypatch, "8.8.8.8")
    assert not is_local_endpoint("openai_compatible", url)  # public address
    assert not is_local_endpoint("openai_compatible", None)


def test_unresolvable_host_not_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ALLOW_PRIVATE_ENV, "1")

    def fail(*a: object, **k: object) -> None:
        raise socket.gaierror

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert not is_local_endpoint("openai_compatible", "http://nowhere.invalid/v1")


def test_embedding_rule() -> None:
    require_local_embedding(True, EmbeddingConfig())
    require_local_embedding(True, EmbeddingConfig(provider="ollama", model="nomic"))
    require_local_embedding(False, EmbeddingConfig(provider="openai", model="m"))
    with pytest.raises(LocalOnlyError, match="local-only: the embedding model must run locally"):
        require_local_embedding(True, EmbeddingConfig(provider="openai", model="m"))


def test_reranker_rule() -> None:
    require_local_reranker(True, "local")
    require_local_reranker(False, "cohere")
    with pytest.raises(LocalOnlyError, match="reranker"):
        require_local_reranker(True, "cohere")


def test_agent_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    require_local_agent(True, "ollama", None)
    require_local_agent(False, "openai", None)
    with pytest.raises(LocalOnlyError, match="model under test"):
        require_local_agent(True, "openai", None)
    monkeypatch.delenv(ALLOW_PRIVATE_ENV, raising=False)
    with pytest.raises(LocalOnlyError):
        require_local_agent(True, "openai_compatible", "http://localhost:1/v1")


def test_platform_llm_rule() -> None:
    assert platform_llm_may_see_kb(False)
    assert not platform_llm_may_see_kb(True)
