"""Agent endpoint validation: syntax at the API, resolved addresses right before connecting."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from pareeksha.adapters.audio_v1 import AudioV1Adapter
from pareeksha.adapters.base import AgentConnectError, AgentTarget, CallContext
from pareeksha.adapters.connection_check import check_connection
from pareeksha.integrations.ssrf import (
    SSRFError,
    agent_allow_private_endpoints,
    check_agent_endpoint_syntax,
    resolve_agent_endpoint,
)
from pareeksha.schemas.agents import AgentCreate, AgentUpdate


def create(url: str | None, adapter: str = "audio_v1") -> AgentCreate:
    return AgentCreate.model_validate({"name": "a", "adapter": adapter, "endpoint_url": url})


@pytest.mark.parametrize(
    "url",
    [
        "ws://mock-agent:8765",
        "ws://localhost:8765/ws",
        "wss://bot.example.com/ws",
        "http://10.0.0.5:9000",
        "https://bot.example.com",
        "ws://[::1]:8765",
    ],
)
def test_legitimate_endpoints_are_accepted(url: str) -> None:
    assert create(url).endpoint_url == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://bot.example.com",
        "gopher://bot.example.com",
        "javascript:alert(1)",
        "bot.example.com",
        "ws://user:pw@bot.example.com/ws",
        "ws://:pw@bot.example.com/ws",
        "ws:///path",
        "ws://bot.example.com:notaport/",
        "http://169.254.169.254/latest/meta-data",
        "ws://169.254.1.1:80",
        "ws://[fe80::1]/",
        "ws://[fd00:ec2::254]/",
        "ws://[::ffff:169.254.169.254]/",
        "prompt://abc",  # only the server may assign this form
    ],
)
def test_bad_endpoints_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        create(url)


def test_prompt_agents_ignore_the_client_endpoint() -> None:
    assert create(None, "prompt").endpoint_url is None
    assert create("whatever", "prompt").endpoint_url == "whatever"  # overwritten server-side


def test_update_validates_the_endpoint() -> None:
    with pytest.raises(ValidationError):
        AgentUpdate(endpoint_url="file:///etc/passwd")
    assert AgentUpdate(endpoint_url="ws://localhost:1").endpoint_url == "ws://localhost:1"
    # a client echoing the server-assigned form back keeps working
    assert AgentUpdate(endpoint_url="prompt://abc").endpoint_url == "prompt://abc"
    assert AgentUpdate(adapter="prompt", endpoint_url="junk").adapter == "prompt"


def test_syntax_check_messages_are_clear() -> None:
    with pytest.raises(ValueError, match="ws, wss, http or https"):
        check_agent_endpoint_syntax("ftp://x")
    with pytest.raises(ValueError, match="credentials"):
        check_agent_endpoint_syntax("ws://a:b@x")


def fixed(*ips: str) -> Any:
    async def resolver(host: str, port: int) -> list[str]:
        return list(ips)

    return resolver


@pytest.mark.parametrize("allow_private", [True, False])
@pytest.mark.parametrize(
    "ip", ["169.254.169.254", "fe80::1", "fd00:ec2::254", "::ffff:169.254.169.254"]
)
async def test_metadata_and_link_local_are_always_refused(ip: str, allow_private: bool) -> None:
    with pytest.raises(SSRFError) as caught:
        await resolve_agent_endpoint(
            "ws://bot.example/ws", fixed("93.184.216.34", ip), allow_private=allow_private
        )
    assert ip not in str(caught.value)


async def test_private_addresses_follow_the_setting() -> None:
    resolved = await resolve_agent_endpoint(
        "ws://mock-agent:8765", fixed("172.18.0.4"), allow_private=True
    )
    assert resolved == ("mock-agent", ["172.18.0.4"], 8765)
    with pytest.raises(SSRFError, match="blocked address"):
        await resolve_agent_endpoint(
            "ws://mock-agent:8765", fixed("172.18.0.4"), allow_private=False
        )
    with pytest.raises(SSRFError):  # one private answer among public ones is enough
        await resolve_agent_endpoint(
            "wss://x", fixed("93.184.216.34", "10.0.0.1"), allow_private=False
        )
    public = await resolve_agent_endpoint("wss://x", fixed("93.184.216.34"), allow_private=False)
    assert public[2] == 443


async def test_literal_loopback_needs_private_allowed() -> None:
    await resolve_agent_endpoint("ws://127.0.0.1:9/", allow_private=True)
    with pytest.raises(SSRFError):
        await resolve_agent_endpoint("ws://127.0.0.1:9/", allow_private=False)


def test_setting_defaults_to_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_ALLOW_PRIVATE_ENDPOINTS", raising=False)
    assert agent_allow_private_endpoints() is True
    for raw in ("false", "0", "No", "off"):
        monkeypatch.setenv("AGENT_ALLOW_PRIVATE_ENDPOINTS", raw)
        assert agent_allow_private_endpoints() is False
    monkeypatch.setenv("AGENT_ALLOW_PRIVATE_ENDPOINTS", "true")
    assert agent_allow_private_endpoints() is True


def target(url: str) -> AgentTarget:
    return AgentTarget(agent_id=uuid.uuid4(), adapter="audio_v1", endpoint_url=url, languages=[])


async def test_adapter_refuses_metadata_address_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pareeksha.adapters.audio_v1.connect", lambda *a, **k: pytest.fail("connected")
    )
    with pytest.raises(AgentConnectError, match="blocked address"):
        await AudioV1Adapter().connect(
            target("ws://169.254.169.254/"), CallContext(call_id=uuid.uuid4())
        )


async def test_adapter_refuses_private_endpoint_when_disallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_ALLOW_PRIVATE_ENDPOINTS", "false")
    with pytest.raises(AgentConnectError, match="blocked address"):
        await AudioV1Adapter().connect(
            target("ws://127.0.0.1:1/"), CallContext(call_id=uuid.uuid4())
        )


async def test_connection_test_reports_a_category_not_the_exception() -> None:
    result = await check_connection(target("ws://127.0.0.1:1/call"))
    assert result.ok is False and result.error == "connect_failed"
    assert result.detail == "cannot connect to agent: could not connect"


async def test_connect_pins_the_validated_address(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_connect(url: str, **kwargs: Any) -> Any:
        seen.update(url=url, **kwargs)
        raise OSError("stop")

    async def resolver(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr("pareeksha.adapters.audio_v1.connect", fake_connect)
    monkeypatch.setattr(
        "pareeksha.adapters.audio_v1.resolve_agent_endpoint",
        lambda url: resolve_agent_endpoint(url, resolver),
    )
    with pytest.raises(AgentConnectError):
        await AudioV1Adapter().connect(
            target("wss://bot.example.com/ws"), CallContext(call_id=uuid.uuid4())
        )
    assert seen["url"] == "wss://bot.example.com/ws"
    assert seen["host"] == "93.184.216.34" and seen["port"] == 443 and seen["proxy"] is None
