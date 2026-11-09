"""Every production provider call goes through ``safe_request`` (one guard, one place)."""

from __future__ import annotations

import functools
import gzip
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from pareeksha.agent_llm import base
from pareeksha.agent_llm.base import MAX_RESPONSE_BYTES, AgentLLMError, AgentMessage
from pareeksha.agent_llm.factory import build_chat_provider
from pareeksha.integrations.ssrf import safe_request

KEY = "sk-test-secret"
OK = {"choices": [{"message": {"content": "hi"}}]}
MSGS = [AgentMessage("user", "hi")]
URL = "https://llm.example.test/v1"


@pytest.fixture(autouse=True)
def _no_private(monkeypatch: pytest.MonkeyPatch) -> None:
    """Helper: no private."""
    monkeypatch.delenv("AGENT_LLM_ALLOW_PRIVATE_URLS", raising=False)


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx.Request], httpx.Response],
    ip: str = "8.8.8.8",
) -> list[httpx.Request]:
    """Route ``safe_request`` to a mock transport and a stub resolver; record the requests."""
    seen: list[httpx.Request] = []

    def record(req: httpx.Request) -> httpx.Response:
        """Helper: record."""
        seen.append(req)
        return handler(req)

    async def resolver(host: str, port: int) -> list[str]:
        """Helper: resolver."""
        return [ip]

    monkeypatch.setattr(
        base,
        "safe_request",
        functools.partial(safe_request, resolver=resolver, transport=httpx.MockTransport(record)),
    )
    return seen


async def _chat(base_url: str | None = URL, provider: Any = "openai_compatible") -> Any:
    """Helper: chat."""
    p = build_chat_provider(provider, api_key=KEY, base_url=base_url)
    return await p.chat(MSGS, [], model="m", temperature=0.1)


async def test_public_host_is_called_pinned_to_the_resolved_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A public host is called at its resolved IP with the original ``Host`` header."""
    seen = _wire(monkeypatch, lambda r: httpx.Response(200, json=OK))
    assert (await _chat()).text == "hi"
    assert seen[0].url.host == "8.8.8.8" and seen[0].headers["host"] == "llm.example.test"
    assert seen[0].headers["content-type"] == "application/json"


async def test_host_resolving_to_loopback_is_rejected_at_request_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host resolving to loopback is refused before any request, as a non-retryable error."""
    seen = _wire(monkeypatch, lambda r: httpx.Response(200, json=OK), ip="127.0.0.1")
    with pytest.raises(AgentLLMError) as exc:
        await _chat()
    assert seen == [] and exc.value.retryable is False
    assert "non-public" in str(exc.value) and KEY not in str(exc.value)


async def test_ollama_default_is_blocked_without_the_private_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plain-http Ollama default is refused without the private-URL flag."""
    seen = _wire(monkeypatch, lambda r: httpx.Response(200, json=OK))
    with pytest.raises(AgentLLMError, match="https"):
        await _chat(None, "ollama")
    assert seen == []


async def test_oversized_response_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A body over the size cap is refused."""
    big = b"x" * (MAX_RESPONSE_BYTES + 1)
    _wire(monkeypatch, lambda r: httpx.Response(200, content=big))
    with pytest.raises(AgentLLMError, match="larger than"):
        await _chat()


async def test_gzip_response_is_decoded_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A gzip body (DeepSeek's default) parses; the decoded body is not decoded a second time."""
    packed = gzip.compress(json.dumps(OK).encode())
    _wire(
        monkeypatch,
        lambda r: httpx.Response(
            200,
            headers={"content-encoding": "gzip", "content-type": "application/json"},
            content=packed,
        ),
    )
    reply = await _chat()
    assert reply.text == "hi"


async def test_redirects_are_not_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirect raises an ``AgentLLMError`` carrying its status and is not followed."""
    seen = _wire(
        monkeypatch,
        lambda r: httpx.Response(302, headers={"location": "https://169.254.169.254/x"}),
    )
    with pytest.raises(AgentLLMError, match="redirect") as exc:
        await _chat()
    assert len(seen) == 1 and exc.value.status == 302


# -- the AGENT_LLM_ALLOW_PRIVATE_URLS opt-in: plain httpx, same no-redirect / size rules ------


def _wire_plain(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    """Helper: wire plain."""
    monkeypatch.setenv("AGENT_LLM_ALLOW_PRIVATE_URLS", "1")
    seen: list[httpx.Request] = []

    def record(req: httpx.Request) -> httpx.Response:
        """Helper: record."""
        seen.append(req)
        return handler(req)

    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", functools.partial(real, transport=httpx.MockTransport(record))
    )
    return seen


async def test_private_opt_in_allows_http_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the private-URL flag the Ollama default on http://localhost is called."""
    seen = _wire_plain(monkeypatch, lambda r: httpx.Response(200, json=OK))
    assert (await _chat(None, "ollama")).text == "hi"
    assert str(seen[0].url) == "http://localhost:11434/v1/chat/completions"


async def test_private_opt_in_still_rejects_redirects_and_big_bodies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The private-URL flag still refuses redirects and oversized response bodies."""
    seen = _wire_plain(
        monkeypatch, lambda r: httpx.Response(307, headers={"location": "http://x/"})
    )
    with pytest.raises(AgentLLMError, match="redirect"):
        await _chat("http://localhost:1/v1")
    assert len(seen) == 1
    big = b"x" * (MAX_RESPONSE_BYTES + 1)
    _wire_plain(monkeypatch, lambda r: httpx.Response(200, content=big))
    with pytest.raises(AgentLLMError, match="larger than"):
        await _chat("http://localhost:1/v1")


async def test_private_opt_in_decodes_gzip_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The plain-httpx path also returns the decoded body without decoding it twice."""
    packed = gzip.compress(json.dumps(OK).encode())
    _wire_plain(
        monkeypatch,
        lambda r: httpx.Response(200, headers={"content-encoding": "gzip"}, content=packed),
    )
    assert (await _chat("http://localhost:1/v1")).text == "hi"


# -- reasoning models reject a non-default temperature ---------------------------------------


async def test_openai_retries_without_temperature_when_rejected() -> None:
    """A 400 that names ``temperature`` is retried once without it."""
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        """Answer 400 to a body that sets ``temperature`` and 200 otherwise, recording each body."""
        bodies.append(json.loads(req.content))
        if "temperature" in bodies[-1]:
            msg = "Unsupported value: 'temperature' does not support 0.1 with this model."
            return httpx.Response(400, json={"error": {"message": msg}})
        return httpx.Response(200, json=OK)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = build_chat_provider("openai", api_key=KEY, http=http)
    assert (await p.chat(MSGS, [], model="o3", temperature=0.1)).text == "hi"
    assert "temperature" in bodies[0] and "temperature" not in bodies[1] and len(bodies) == 2


async def test_other_400s_are_not_retried() -> None:
    """Other 400s raise at once; the provider message is kept apart from the error text."""
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        """Helper: handler."""
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad model"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    p = build_chat_provider("openai", api_key=KEY, http=http)
    with pytest.raises(AgentLLMError, match="HTTP 400") as ei:
        await p.chat(MSGS, [], model="x", temperature=0.1)
    assert len(calls) == 1
    assert "bad model" not in str(ei.value) and ei.value.provider_message == "bad model"
