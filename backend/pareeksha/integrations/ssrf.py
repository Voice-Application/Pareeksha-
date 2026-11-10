"""SSRF guard and safe fetch (FR-IN-5, NFR-15).

Rules: https only; every address the host resolves to must be public (not private, loopback,
link-local, multicast, reserved or unspecified); the connection is pinned to the validated IP so a
second DNS answer cannot redirect it (TLS still verifies the original hostname via SNI);
redirects are never followed; size and content-type are enforced while streaming.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import httpx

log = logging.getLogger(__name__)

Resolver = Callable[[str, int], Awaitable[list[str]]]

DEFAULT_MAX_BYTES = 10 * 1024 * 1024

#: Development switch: let the platform call a receiver on a private/loopback address (still https).
DEV_ALLOW_PRIVATE_ENV = "PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS"


def dev_allow_private() -> bool:
    """True when ``PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1`` turns the public-address check off."""
    return os.environ.get(DEV_ALLOW_PRIVATE_ENV) == "1"


class SSRFError(Exception):
    """The URL is not allowed (scheme, host, resolved address, size or content-type)."""


async def system_resolver(host: str, port: int) -> list[str]:
    """System resolver."""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFError(f"cannot resolve {host!r}") from exc
    return sorted({str(info[4][0]) for info in infos})


_V4 = ipaddress.IPv4Network
_V6 = ipaddress.IPv6Network

#: Not globally routable (or reserved) space that ``is_global`` alone has let through on some
#: Python versions: "this network", CGNAT, IETF/benchmarking, multicast and the reserved block.
_REFUSED_V4 = tuple(
    _V4(n)
    for n in (
        "0.0.0.0/8",
        "100.64.0.0/10",
        "192.0.0.0/24",
        "198.18.0.0/15",
        "224.0.0.0/4",
        "240.0.0.0/4",
    )
)
#: NAT64 local-use, discard, IETF protocol space (includes Teredo 2001::/32), documentation,
#: unique-local, link-local, deprecated site-local and multicast.
_REFUSED_V6 = tuple(
    _V6(n)
    for n in (
        "64:ff9b:1::/48",
        "100::/64",
        "2001::/23",
        "2001:db8::/32",
        "3fff::/20",
        "fc00::/7",
        "fe80::/10",
        "fec0::/10",
        "ff00::/8",
    )
)
#: IPv6 forms that carry an IPv4 address in the low 32 bits.
_V4_IN_LOW_BITS = (_V6("::/96"), _V6("64:ff9b::/96"))
_6TO4 = _V6("2002::/16")

#: Destinations an agent endpoint may never use, even when private addresses are allowed:
#: link-local (includes the 169.254.169.254 metadata service) and the AWS IPv6 metadata address.
_ENDPOINT_BLOCKED = (_V4("169.254.0.0/16"), _V6("fe80::/10"), _V6("fd00:ec2::254/128"))


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address an IPv6 form wraps (mapped, compatible, NAT64, 6to4), if any."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if any(ip in net for net in _V4_IN_LOW_BITS):
        return ipaddress.IPv4Address(ip.packed[-4:])
    if ip in _6TO4:
        return ipaddress.IPv4Address(ip.packed[2:6])
    return None


def _addresses_to_check(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """``ip`` plus every IPv4 address embedded in it, recursively."""
    found: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [ip]
    while isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_ipv4(ip)
        if inner is None:
            break
        found.append(inner)
        ip = inner
    return found


def _parse(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return None


def _is_global_unicast(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv4Address):
        if any(ip in net for net in _REFUSED_V4):
            return False
    elif any(ip in net for net in _REFUSED_V6):
        return False
    return ip.is_global and not ip.is_multicast


def is_public_ip(value: str) -> bool:
    """True only for globally routable unicast addresses.

    IPv6 forms that wrap an IPv4 address (mapped, compatible, NAT64, 6to4) are public only when
    the wrapped address is too; Teredo, site-local, unique-local and similar ranges never are.
    """
    ip = _parse(value)
    if ip is None:
        return False
    return all(_is_global_unicast(candidate) for candidate in _addresses_to_check(ip))


def is_blocked_endpoint_ip(value: str) -> bool:
    """True for link-local / cloud-metadata addresses (also when wrapped in an IPv6 form)."""
    ip = _parse(value)
    if ip is None:
        return True
    return any(
        candidate in net
        for candidate in _addresses_to_check(ip)
        for net in _ENDPOINT_BLOCKED
        if candidate.version == net.version
    )


def _is_ip_literal(host: str) -> bool:
    """Is ip literal."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


async def resolve_public(
    url: str, resolver: Resolver = system_resolver, *, allow_private: bool = False
) -> tuple[str, str, int]:
    """Validate ``url``; return ``(host, pinned_ip, port)``. Raises ``SSRFError``.

    ``allow_private`` skips only the public-address check (https, no credentials and IP pinning
    still apply). It exists for local development and acceptance runs against a receiver on
    localhost; connectors enable it only through ``PAREEKSHA_DEV_ALLOW_PRIVATE_TARGETS=1``.
    """
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
        if not allow_private and not is_public_ip(address):
            log.warning("ssrf: %r resolved to non-public address %s", host, address)
            raise SSRFError(f"{host!r} resolves to a non-public address")
    return host, addresses[0], port


AGENT_ALLOW_PRIVATE_ENV = "AGENT_ALLOW_PRIVATE_ENDPOINTS"
_AGENT_SCHEMES = {"ws": 80, "wss": 443, "http": 80, "https": 443}


def agent_allow_private_endpoints() -> bool:
    """``AGENT_ALLOW_PRIVATE_ENDPOINTS`` (default true): agents may live on private addresses.

    Operators hosting Pareeksha for other people set it to false so agent endpoints must be
    public. Link-local and cloud-metadata destinations are refused either way."""
    raw = os.environ.get(AGENT_ALLOW_PRIVATE_ENV, "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def check_agent_endpoint_syntax(url: str, *, allow_prompt: bool = False) -> None:
    """Checks that need no DNS: scheme, host, credentials, port and a blocked IP literal.

    Raises ``ValueError``. ``allow_prompt`` accepts the internal ``prompt://`` form."""
    try:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if allow_prompt and scheme == "prompt":
            return
        if scheme not in _AGENT_SCHEMES:
            raise ValueError("endpoint_url must use ws, wss, http or https")
        host = parts.hostname
        _ = parts.port
    except ValueError as exc:
        if str(exc).startswith("endpoint_url"):
            raise
        raise ValueError("endpoint_url is not a valid URL") from exc
    if not host:
        raise ValueError("endpoint_url has no host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("credentials in endpoint_url are not allowed")
    if _is_ip_literal(host) and is_blocked_endpoint_ip(host):
        raise ValueError("endpoint_url points at a link-local or metadata address")


async def resolve_agent_endpoint(
    url: str, resolver: Resolver = system_resolver, *, allow_private: bool | None = None
) -> tuple[str, list[str], int]:
    """Validate an agent endpoint right before connecting; return ``(host, addresses, port)``.

    Every resolved address must avoid link-local / metadata space, and be public too unless
    private endpoints are allowed. Callers connect to one of the returned addresses (not the
    host name) so a later DNS answer cannot redirect the connection. Raises ``SSRFError``."""
    if allow_private is None:
        allow_private = agent_allow_private_endpoints()
    try:
        check_agent_endpoint_syntax(url)
    except ValueError as exc:
        raise SSRFError(str(exc)) from exc
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or _AGENT_SCHEMES[parts.scheme.lower()]
    addresses = [host] if _is_ip_literal(host) else await resolver(host, port)
    if not addresses:
        raise SSRFError("endpoint host did not resolve")
    for address in addresses:
        if is_blocked_endpoint_ip(address) or (not allow_private and not is_public_ip(address)):
            log.warning("agent endpoint %r resolved to blocked address %s", host, address)
            raise SSRFError("endpoint resolves to a blocked address")
    return host, addresses, port


#: Headers that describe the wire body; they no longer apply once the body is read and decoded.
_WIRE_HEADERS = ("content-encoding", "content-length", "transfer-encoding")


def buffered_response(response: httpx.Response, content: bytes) -> httpx.Response:
    """A complete response holding ``content``, the already *decoded* body of ``response``.

    ``aiter_bytes`` undoes gzip / br / zstd, so the wire headers are dropped: keeping
    ``Content-Encoding`` would make httpx decode the plain body again (``DecodingError``).
    """
    headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in _WIRE_HEADERS]
    return httpx.Response(
        response.status_code, headers=headers, content=content, request=response.request
    )


def _pinned_url(url: str, ip: str, port: int) -> str:
    """Pinned url."""
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
    allow_private: bool = False,
) -> httpx.Response:
    """Send one request to a validated public host and return the (size-limited) response.

    ``transport`` exists so tests can observe the pinned request without a network
    (an ``httpx.MockTransport``); production uses the default transport.
    """
    host, ip, port = await resolve_public(url, resolver, allow_private=allow_private)
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
        return buffered_response(response, b"".join(chunks))
