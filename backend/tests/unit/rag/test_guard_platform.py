"""The platform-LLM rule and the Ollama local-endpoint rule (both decided only in guard.py)."""

from __future__ import annotations

import socket

import pytest

from pareeksha.rag import guard
from pareeksha.rag.guard import (
    PLATFORM_LLM_REFUSAL,
    LocalOnlyError,
    is_local_endpoint,
    require_platform_llm_allowed,
)


def _resolve(monkeypatch: pytest.MonkeyPatch, *ips: str) -> None:
    infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: infos)


def _private_urls(monkeypatch: pytest.MonkeyPatch, allowed: bool) -> None:
    monkeypatch.setattr(guard, "allow_private_urls", lambda: allowed)


def test_platform_llm_refuses_a_local_only_kb() -> None:
    require_platform_llm_allowed(False)
    with pytest.raises(LocalOnlyError) as exc:
        require_platform_llm_allowed(True)
    assert str(exc.value) == PLATFORM_LLM_REFUSAL
    assert "hosted LLM" in PLATFORM_LLM_REFUSAL
    assert "chunk browsing still work" in PLATFORM_LLM_REFUSAL


def test_ollama_default_url_is_local_without_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    _private_urls(monkeypatch, False)
    assert is_local_endpoint("ollama", None)
    assert is_local_endpoint("ollama", "")


def test_ollama_with_a_base_url_must_resolve_private(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hosted endpoint behind provider='ollama' must not pass as local."""
    url = "https://ollama.example.com/v1"
    _private_urls(monkeypatch, True)
    _resolve(monkeypatch, "8.8.8.8")
    assert not is_local_endpoint("ollama", url)  # public address
    assert not is_local_endpoint("ollama", "not a url")  # no host
    _resolve(monkeypatch, "10.0.0.5")
    assert is_local_endpoint("ollama", url)  # private address
    _private_urls(monkeypatch, False)
    assert not is_local_endpoint("ollama", url)  # same opt-in as openai_compatible
    assert not is_local_endpoint("ollama", "http://localhost:11434")


def test_ollama_mixed_public_and_private_answers_are_not_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _private_urls(monkeypatch, True)
    _resolve(monkeypatch, "10.0.0.5", "8.8.8.8")
    assert not is_local_endpoint("ollama", "https://rebind.example.com")
