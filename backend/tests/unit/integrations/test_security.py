"""INT-01: Fernet, HMAC signing and the SSRF guard."""

from __future__ import annotations

import httpx
import pytest
from cryptography.fernet import Fernet

from pareeksha.integrations.crypto import SecretBox, SecretDecryptError, redact
from pareeksha.integrations.signing import (
    SignatureError,
    compute_signature,
    sign_headers,
    verify_signature,
)
from pareeksha.integrations.ssrf import (
    Resolver,
    SSRFError,
    is_public_ip,
    resolve_public,
    safe_request,
)

BODY = b'{"a":1}'
PUBLIC = "93.184.216.34"


def fixed(*ips: str) -> Resolver:
    async def resolver(host: str, port: int) -> list[str]:
        return list(ips)

    return resolver


def test_fernet_roundtrip_and_ciphertext_hides_secret() -> None:
    box = SecretBox(Fernet.generate_key())
    token = box.encrypt({"token": "super-secret-value"})
    assert "super-secret-value" not in token
    assert box.decrypt(token) == {"token": "super-secret-value"}
    assert redact({"token": "x", "empty": ""}) == {"token": True, "empty": False}


def test_fernet_wrong_key_and_bad_key() -> None:
    token = SecretBox(Fernet.generate_key()).encrypt({"a": "b"})
    with pytest.raises(SecretDecryptError):
        SecretBox(Fernet.generate_key()).decrypt(token)
    with pytest.raises(ValueError, match="Fernet key"):
        SecretBox("not-a-key")


def test_sign_and_verify_ok() -> None:
    headers = sign_headers("s3cret", BODY, timestamp=1000)
    verify_signature(headers, BODY, "s3cret", now=1100)
    assert headers["X-Pareeksha-Signature"] == "v1=" + compute_signature("s3cret", 1000, BODY)


def test_verify_rejects_bad_signature_tampered_body_stale_and_future() -> None:
    headers = sign_headers("s3cret", BODY, timestamp=1000)
    with pytest.raises(SignatureError, match="mismatch"):
        verify_signature(headers, BODY, "other", now=1000)
    with pytest.raises(SignatureError, match="mismatch"):
        verify_signature(headers, b'{"a":2}', "s3cret", now=1000)
    with pytest.raises(SignatureError, match="tolerance"):
        verify_signature(headers, BODY, "s3cret", now=1000 + 301)
    with pytest.raises(SignatureError, match="tolerance"):
        verify_signature(headers, BODY, "s3cret", now=1000 - 301)
    verify_signature(headers, BODY, "s3cret", now=1000 + 300)


def test_verify_rejects_missing_and_malformed() -> None:
    with pytest.raises(SignatureError, match="missing"):
        verify_signature({}, BODY, "s", now=0)
    with pytest.raises(SignatureError, match="malformed"):
        verify_signature({"X-Pareeksha-Timestamp": "x", "X-Pareeksha-Signature": "v1=a"}, BODY, "s")
    with pytest.raises(SignatureError, match="no v1"):
        verify_signature(
            {"x-pareeksha-timestamp": "5", "x-pareeksha-signature": "v2=abc"}, BODY, "s", now=5
        )


def test_secret_rotation_accepts_either_secret() -> None:
    both = sign_headers(["new-secret", "old-secret"], BODY, timestamp=50)
    assert both["X-Pareeksha-Signature"].count("v1=") == 2
    verify_signature(both, BODY, "old-secret", now=50)
    verify_signature(both, BODY, ["x", "new-secret"], now=50)
    with pytest.raises(ValueError):
        sign_headers([], BODY)


def test_sign_headers_default_timestamp_is_now() -> None:
    verify_signature(sign_headers("s", BODY), BODY, "s")


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.3.1",
        "192.168.1.1",
        "169.254.169.254",
        "0.0.0.0",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:10.0.0.1",
        "224.0.0.1",
        "100.64.0.1",
        "garbage",
    ],
)
def test_private_ranges_are_not_public(ip: str) -> None:
    assert not is_public_ip(ip)


def test_public_ip_ok() -> None:
    assert is_public_ip(PUBLIC)
    assert is_public_ip("2606:4700:4700::1111")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/x",
        "https://user:pw@example.com/",
        "https:///x",
        "ftp://example.com",
        "https://127.0.0.1/",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/",
        "https://example.com:notaport/",
    ],
)
async def test_resolve_public_rejects(url: str) -> None:
    with pytest.raises(SSRFError):
        await resolve_public(url, fixed(PUBLIC))


async def test_resolve_public_rejects_private_dns_answer_even_if_one_is_public() -> None:
    with pytest.raises(SSRFError, match="non-public"):
        await resolve_public("https://evil.example/", fixed(PUBLIC, "10.0.0.1"))


async def test_resolve_public_empty_answer_and_ok() -> None:
    with pytest.raises(SSRFError, match="did not resolve"):
        await resolve_public("https://a.example/", fixed())
    assert await resolve_public("https://a.example:8443/x", fixed(PUBLIC)) == (
        "a.example",
        PUBLIC,
        8443,
    )


async def test_system_resolver_unresolvable() -> None:
    with pytest.raises(SSRFError, match="cannot resolve"):
        await resolve_public("https://nonexistent.invalid/")


async def test_localhost_via_real_dns_is_blocked() -> None:
    with pytest.raises(SSRFError, match="non-public"):
        await resolve_public("https://localhost/")


async def test_safe_request_pins_ip_and_sets_host_and_sni() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host"] = request.headers["host"]
        seen["sni"] = request.extensions["sni_hostname"]
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "audio/mpeg"})

    resp = await safe_request(
        "GET",
        "https://rec.example.com/a.mp3?x=1",
        resolver=fixed(PUBLIC),
        transport=httpx.MockTransport(handler),
        allowed_content_types=("audio/*",),
    )
    assert resp.status_code == 200
    assert seen == {
        "url": f"https://{PUBLIC}/a.mp3?x=1",
        "host": "rec.example.com",
        "sni": "rec.example.com",
    }


async def test_safe_request_ipv6_pin_and_custom_port_host_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["host"] = request.headers["host"]
        return httpx.Response(204)

    await safe_request(
        "POST",
        "https://h.example:8443",
        resolver=fixed("2606:4700:4700::1111"),
        transport=httpx.MockTransport(handler),
        content=b"x",
    )
    assert seen["url"].startswith("https://[2606:4700:4700::1111]:8443/")
    assert seen["host"] == "h.example:8443"


async def test_safe_request_enforces_content_type_and_size() -> None:
    def big(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 50, headers={"content-type": "audio/wav"})

    def declared(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "audio/wav", "content-length": "999"})

    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})

    url = "https://a.example/"
    with pytest.raises(SSRFError, match="larger"):
        await safe_request(
            "GET", url, resolver=fixed(PUBLIC), max_bytes=10, transport=httpx.MockTransport(big)
        )
    with pytest.raises(SSRFError, match="larger"):
        await safe_request(
            "GET",
            url,
            resolver=fixed(PUBLIC),
            max_bytes=10,
            transport=httpx.MockTransport(declared),
        )
    with pytest.raises(SSRFError, match="content-type"):
        await safe_request(
            "GET",
            url,
            resolver=fixed(PUBLIC),
            allowed_content_types=("audio/*", "application/octet-stream"),
            transport=httpx.MockTransport(html),
        )


async def test_safe_request_does_not_follow_redirects_to_internal() -> None:
    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://169.254.169.254/"})

    resp = await safe_request(
        "GET",
        "https://a.example/",
        resolver=fixed(PUBLIC),
        transport=httpx.MockTransport(redirect),
    )
    assert resp.status_code == 302
