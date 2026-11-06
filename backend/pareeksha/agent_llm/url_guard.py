"""Base-URL SSRF guard for user-supplied agent-LLM endpoints."""

from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit

from pareeksha.integrations.ssrf import is_public_ip

ALLOW_PRIVATE_ENV = "AGENT_LLM_ALLOW_PRIVATE_URLS"


def allow_private_urls() -> bool:
    """True when ``AGENT_LLM_ALLOW_PRIVATE_URLS`` is truthy (local Ollama, dev servers)."""
    return os.environ.get(ALLOW_PRIVATE_ENV, "").strip().lower() in ("1", "true", "yes")


def check_base_url(url: str, *, allow_private: bool) -> None:
    """Raise ``ValueError`` for non-https URLs (http too when ``allow_private``) and, unless
    ``allow_private``, for hosts that resolve to loopback/private/link-local/metadata addresses.
    Mirrors what ``safe_request`` enforces at request time."""
    parts = urlsplit(url)
    if parts.scheme not in (("http", "https") if allow_private else ("https",)):
        raise ValueError("base_url must use https (set AGENT_LLM_ALLOW_PRIVATE_URLS for http)")
    host = parts.hostname
    if not host:
        raise ValueError("base_url has no host")
    if parts.username or parts.password:
        raise ValueError("credentials in base_url are not allowed")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve {host!r}") from exc
    for info in infos:
        if not is_public_ip(str(info[4][0])):
            raise ValueError(f"base_url host {host!r} resolves to a non-public address")
