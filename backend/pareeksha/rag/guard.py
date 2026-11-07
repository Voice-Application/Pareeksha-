"""The one place that decides the local-only rule for knowledge bases."""

from __future__ import annotations

import socket
from urllib.parse import urlsplit

from pareeksha.agent_llm.url_guard import allow_private_urls
from pareeksha.integrations.ssrf import is_public_ip
from pareeksha.schemas.rag import EmbeddingConfig


class LocalOnlyError(Exception):
    """A local-only knowledge base was asked to use something hosted."""


def _refuse(what: str) -> LocalOnlyError:
    return LocalOnlyError(f"knowledge base is local-only: {what} must run locally")


def _resolves_non_public(base_url: str) -> bool:
    host = urlsplit(base_url).hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    return bool(infos) and not any(is_public_ip(str(i[4][0])) for i in infos)


def is_local_endpoint(provider: str, base_url: str | None) -> bool:
    if provider == "local":
        return True
    if provider == "ollama" and not base_url:  # the default, http://localhost:11434
        return True
    if provider not in ("ollama", "openai_compatible") or not base_url or not allow_private_urls():
        return False
    return _resolves_non_public(base_url)


def require_local_embedding(kb_local_only: bool, cfg: EmbeddingConfig) -> None:
    if kb_local_only and not is_local_endpoint(cfg.provider, cfg.base_url):
        raise _refuse("the embedding model")


def require_local_reranker(kb_local_only: bool, provider: str) -> None:
    if kb_local_only and provider != "local":
        raise _refuse("the reranker")


def require_local_agent(kb_local_only: bool, provider: str, base_url: str | None) -> None:
    if kb_local_only and not is_local_endpoint(provider, base_url):
        raise _refuse("the model under test")


def platform_llm_may_see_kb(kb_local_only: bool) -> bool:
    """The platform LLM (DeepSeek/Gemini) is always hosted."""
    return not kb_local_only


PLATFORM_LLM_REFUSAL = (
    "This knowledge base is local-only. Test runs send the agent's answers to Pareeksha's hosted "
    "LLM (simulated caller and judge), so they are disabled until a local Pareeksha LLM is "
    "configured. Upload, index builds and chunk browsing still work."
)


def require_platform_llm_allowed(kb_local_only: bool) -> None:
    """A test run's transcript carries KB text to the hosted caller brain and judge."""
    if not platform_llm_may_see_kb(kb_local_only):
        raise LocalOnlyError(PLATFORM_LLM_REFUSAL)
