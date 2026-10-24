"""SSRF guard and safe fetch (FR-IN-5, NFR-15).

Rules: https only; every address the host resolves to must be public (not private, loopback,
link-local, multicast, reserved or unspecified); the connection is pinned to the validated IP so a
second DNS answer cannot redirect it (TLS still verifies the original hostname via SNI);
redirects are never followed; size and content-type are enforced while streaming.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

Resolver = Callable[[str, int], Awaitable[list[str]]]

DEFAULT_MAX_BYTES = 10 * 1024 * 1024


class SSRFError(Exception):
    """The URL is not allowed (scheme, host, resolved address, size or content-type)."""


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFError(f"cannot resolve {host!r}") from exc
    return sorted({str(info[4][0]) for info in infos})


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def resolve_public(url: str, resolver: Resolver = system_resolver) -> tuple[str, str, int]:
    """Validate ``url``; return ``(host, pinned_ip, port)``. Raises ``SSRFError``."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise SSRFError("only https URLs are allowed")
    host = parts.hostname
    if not host:
        raise SSRFError("URL has no host")
    if parts.username or parts.password:
        raise SSRFError("credentials in URL are not allowed")
    try:
        port = parts.port or 443
    except ValueError as exc:
        raise SSRFError("invalid port") from exc
    addresses = [host] if _is_ip_literal(host) else await resolver(host, port)
    if not addresses:
        raise SSRFError(f"{host!r} did not resolve")
    for address in addresses:
        if not is_public_ip(address):
            raise SSRFError(f"{host!r} resolves to a non-public address ({address})")
    return host, addresses[0], port


def _pinned_url(url: str, ip: str, port: int) -> str:
    parts = urlsplit(url)
    netloc = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


async def safe_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
    timeout_s: float = 10.0,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allowed_content_types: tuple[str, ...] | None = None,
    resolver: Resolver = system_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.Response:
    """Send one request to a validated public host and return the (size-limited) response.

    ``transport`` exists so tests can observe the pinned request without a network
    (an ``httpx.MockTransport``); production uses the default transport.
    """
    host, ip, port = await resolve_public(url, resolver)
    request_headers = dict(headers or {})
    request_headers["Host"] = host if port == 443 else f"{host}:{port}"
    target = _pinned_url(url, ip, port)
    async with (
        httpx.AsyncClient(timeout=timeout_s, follow_redirects=False, transport=transport) as client,
        client.stream(
            method,
            target,
            headers=request_headers,
            content=content,
            extensions={"sni_hostname": host},
        ) as response,
    ):
        if allowed_content_types is not None:
            ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if not any(
                ctype == allowed or (allowed.endswith("/*") and ctype.startswith(allowed[:-1]))
                for allowed in allowed_content_types
            ):
                raise SSRFError(f"content-type {ctype!r} not allowed")
        declared = response.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > max_bytes:
            raise SSRFError(f"response larger than {max_bytes} bytes")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise SSRFError(f"response larger than {max_bytes} bytes")
            chunks.append(chunk)
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=b"".join(chunks),
            request=response.request,
        )
