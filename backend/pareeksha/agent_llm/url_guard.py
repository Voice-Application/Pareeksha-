"""Base-URL SSRF guard for user-supplied agent-LLM endpoints."""

from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit

from pareeksha.integrations.ssrf import is_public_ip

ALLOW_PRIVATE_ENV = "AGENT_LLM_ALLOW_PRIVATE_URLS"
OLLAMA_BASE_URL_ENV = "OLLAMA_BASE_URL"
OLLAMA_DEFAULT_URL = "http://localhost:11434/v1"


def allow_private_urls() -> bool:
    """True when ``AGENT_LLM_ALLOW_PRIVATE_URLS`` is truthy (local Ollama, dev servers)."""
    return os.environ.get(ALLOW_PRIVATE_ENV, "").strip().lower() in ("1", "true", "yes")


def ollama_base_url() -> str:
    """Where Ollama is when a config gives no ``base_url``: ``OLLAMA_BASE_URL``, else localhost.

    In Docker, ``localhost`` is the container itself, so compose sets this to the host
    (``http://host.docker.internal:11434/v1``). Read per call, so tests can change it."""
    return (os.environ.get(OLLAMA_BASE_URL_ENV) or "").strip().rstrip("/") or OLLAMA_DEFAULT_URL


def _origin(url: str) -> tuple[str, str, int | None, str] | None:
    try:
        p = urlsplit(url)
        return p.scheme.lower(), (p.hostname or "").lower(), p.port, p.path.rstrip("/")
    except ValueError:
        return None


def is_operator_ollama(url: str | None) -> bool:
    """True when ``url`` is on the ``OLLAMA_BASE_URL`` the operator set: same scheme, host and
    port, under its path, with no query, fragment or ``..``. That server is trusted like a local
    model (plain http, a private address) without ``AGENT_LLM_ALLOW_PRIVATE_URLS``, which would
    open every private address to tenant-supplied URLs."""
    configured = (os.environ.get(OLLAMA_BASE_URL_ENV) or "").strip()
    if not configured or not url or "?" in url or "#" in url or ".." in url:
        return False
    mine, theirs = _origin(configured), _origin(url)
    if mine is None or theirs is None or not mine[1]:
        return False
    return theirs[:3] == mine[:3] and (theirs[3] + "/").startswith(mine[3] + "/")


def check_base_url(url: str, *, allow_private: bool) -> None:
    """Raise ``ValueError`` for non-https URLs (http too when ``allow_private``) and, unless
    ``allow_private``, for hosts that resolve to loopback/private/link-local/metadata addresses.
    Mirrors what ``safe_request`` enforces at request time. The operator's ``OLLAMA_BASE_URL``
    (see :func:`is_operator_ollama`) is always accepted."""
    if is_operator_ollama(url):
        return
    parts = urlsplit(url)
    if parts.scheme not in (("http", "https") if allow_private else ("https",)):
        raise ValueError("base_url must use https (set AGENT_LLM_ALLOW_PRIVATE_URLS for http)")
    host = parts.hostname
    if not host:
        raise ValueError("base_url has no host")
    if parts.username or parts.password:
        raise ValueError("credentials in base_url are not allowed")
    # checked on the raw string: urlsplit drops an empty "?" or "#"
    if "?" in url or "#" in url:
        raise ValueError("base_url must not contain a query string or fragment")
    if allow_private:
        return
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve {host!r}") from exc
    for info in infos:
        if not is_public_ip(str(info[4][0])):
            raise ValueError(f"base_url host {host!r} resolves to a non-public address")
