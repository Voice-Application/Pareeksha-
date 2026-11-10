"""SSRF address filter: IPv6 forms that wrap IPv4, and non-global ranges."""

from __future__ import annotations

import pytest

from pareeksha.integrations.ssrf import (
    SSRFError,
    is_blocked_endpoint_ip,
    is_public_ip,
    resolve_public,
)

NOT_PUBLIC = [
    # IPv4
    "0.0.0.0",
    "0.1.2.3",
    "127.0.0.1",
    "10.1.2.3",
    "100.64.0.1",
    "100.127.255.254",
    "169.254.169.254",
    "172.16.0.1",
    "192.0.0.8",
    "192.168.0.1",
    "198.18.0.1",
    "198.19.255.255",
    "224.0.0.1",
    "239.255.255.250",
    "240.0.0.1",
    "255.255.255.255",
    # IPv6
    "::",
    "::1",
    "fe80::1",
    "fec0::1",
    "fc00::1",
    "fd12:3456::1",
    "ff02::1",
    "2001:db8::1",
    "2001::1",  # Teredo
    "100::1",
    # wrapped IPv4
    "::ffff:10.0.0.1",
    "::ffff:169.254.169.254",
    "::10.0.0.1",  # IPv4-compatible
    "::127.0.0.1",
    "64:ff9b::10.0.0.1",  # NAT64
    "64:ff9b::a9fe:a9fe",
    "64:ff9b:1::1",  # NAT64 local-use
    "2002:0a00:0001::1",  # 6to4 of 10.0.0.1
    "2002:7f00:0001::1",
    "2002:0808:0808::1",  # 6to4 is refused outright
    "2002:a9fe:a9fe::1",
    "garbage",
    "",
]

PUBLIC = [
    "93.184.216.34",
    "8.8.8.8",
    "2606:4700:4700::1111",
    "::ffff:8.8.8.8",
    "64:ff9b::808:808",
]


@pytest.mark.parametrize("ip", NOT_PUBLIC)
def test_not_public(ip: str) -> None:
    assert not is_public_ip(ip)


@pytest.mark.parametrize("ip", PUBLIC)
def test_public(ip: str) -> None:
    assert is_public_ip(ip)


@pytest.mark.parametrize(
    ("ip", "blocked"),
    [
        ("169.254.169.254", True),
        ("169.254.0.1", True),
        ("fe80::1", True),
        ("fd00:ec2::254", True),
        ("::ffff:169.254.169.254", True),
        ("64:ff9b::a9fe:a9fe", True),
        ("2002:a9fe:a9fe::1", True),
        ("not-an-ip", True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("::1", False),
        ("fd00:ec2::1", False),
        ("8.8.8.8", False),
    ],
)
def test_blocked_endpoint_ip(ip: str, blocked: bool) -> None:
    assert is_blocked_endpoint_ip(ip) is blocked


async def test_error_message_does_not_reveal_resolved_address() -> None:
    async def resolver(host: str, port: int) -> list[str]:
        return ["10.9.8.7"]

    with pytest.raises(SSRFError) as caught:
        await resolve_public("https://internal.example/", resolver)
    assert "10.9.8.7" not in str(caught.value)
