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


def is_local_endpoint(provider: str, base_url: str | None) -> bool:
    if provider in ("ollama", "local"):
        return True
    if provider != "openai_compatible" or not base_url or not allow_private_urls():
        return False
    host = urlsplit(base_url).hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    return bool(infos) and not any(is_public_ip(str(i[4][0])) for i in infos)


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
