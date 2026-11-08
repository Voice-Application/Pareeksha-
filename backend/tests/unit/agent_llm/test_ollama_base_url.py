"""``OLLAMA_BASE_URL``: where Ollama is by default, and the one private URL that is trusted
without ``AGENT_LLM_ALLOW_PRIVATE_URLS`` (embeddings, chat, the local-only guard)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pareeksha.agent_llm import base
from pareeksha.agent_llm.factory import build_chat_provider
from pareeksha.agent_llm.url_guard import check_base_url, is_operator_ollama, ollama_base_url
from pareeksha.integrations.ssrf import SSRFError
from pareeksha.rag.embeddings import build_embedder
from pareeksha.rag.guard import is_local_endpoint, require_local_embedding
from pareeksha.schemas.rag import EmbeddingConfig

HOST = "http://host.docker.internal:11434/v1"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_LLM_ALLOW_PRIVATE_URLS", raising=False)


def test_default_is_localhost_and_the_env_overrides_it(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ollama_base_url() == "http://localhost:11434/v1"
    monkeypatch.setenv("OLLAMA_BASE_URL", f"  {HOST}/ ")
    assert ollama_base_url() == HOST


@pytest.mark.parametrize(
    ("url", "trusted"),
    [
        (HOST, True),
        (f"{HOST}/", True),
        (f"{HOST}/embeddings", True),
        ("HTTP://HOST.DOCKER.INTERNAL:11434/v1", True),
        ("http://host.docker.internal:11435/v1", False),  # another port
        ("https://host.docker.internal:11434/v1", False),  # another scheme
        ("http://169.254.169.254:11434/v1", False),  # another host
        ("http://host.docker.internal:11434/api", False),  # outside the configured path
        ("http://host.docker.internal:11434/v1x", False),
        (f"{HOST}/../api/create", False),
        (f"{HOST}?x=1", False),
        (f"{HOST}#frag", False),
        ("http://user:secret@host.docker.internal:11434/v1", False),  # credentials never trusted
        ("http://user@host.docker.internal:11434/v1", False),
        ("http://host.docker.internal:notaport/v1", False),
        (None, False),
    ],
)
def test_only_the_configured_server_is_trusted(
    monkeypatch: pytest.MonkeyPatch, url: str | None, trusted: bool
) -> None:
    assert not is_operator_ollama(HOST)  # nothing is trusted until the operator sets it
    monkeypatch.setenv("OLLAMA_BASE_URL", HOST)
    assert is_operator_ollama(url) is trusted


async def test_embeddings_and_chat_default_to_the_configured_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no base_url, both the embedder and the chat provider call OLLAMA_BASE_URL."""
    monkeypatch.setenv("OLLAMA_BASE_URL", HOST)
    seen: list[str] = []

    def reply(req: httpx.Request) -> httpx.Response:
        """Answer /embeddings with one vector and /chat/completions with a short reply."""
        seen.append(str(req.url))
        body = json.loads(req.content)
        if req.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})
        assert body["model"] == "qwen3:8b"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}},
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(reply))
    cfg = EmbeddingConfig(provider="ollama", model="qwen3-embedding:0.6b")
    res = await build_embedder(cfg, api_key=None, http=http).embed(["a"], kind="query")
    assert res.vectors == [[1.0]]
    chat = build_chat_provider("ollama", api_key=None, http=http)
    await chat.chat([base.AgentMessage("user", "hi")], [], model="qwen3:8b", temperature=0.0)
    assert seen == [f"{HOST}/embeddings", f"{HOST}/chat/completions"]


def test_the_configured_server_counts_as_local(monkeypatch: pytest.MonkeyPatch) -> None:
    assert is_local_endpoint("ollama", None)
    assert not is_local_endpoint("ollama", HOST)  # a private URL, and nothing allows it
    monkeypatch.setenv("OLLAMA_BASE_URL", HOST)
    assert is_local_endpoint("ollama", HOST)
    require_local_embedding(True, EmbeddingConfig(provider="ollama", model="m", base_url=HOST))
    # trust is for Ollama only: the same URL as an openai_compatible endpoint is still private
    assert not is_local_endpoint("openai_compatible", HOST)


def test_base_url_check_accepts_the_configured_server_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_base_url lets the configured server through, never another or one with credentials."""
    with pytest.raises(ValueError, match="https"):
        check_base_url(HOST, allow_private=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", HOST)
    check_base_url(HOST, allow_private=False)
    with pytest.raises(ValueError, match="https"):
        check_base_url("http://host.docker.internal:8080/v1", allow_private=False)
    # the trusted server with credentials falls back to the normal checks, which refuse it
    with pytest.raises(ValueError, match="credentials"):
        check_base_url("http://u:p@host.docker.internal:11434/v1", allow_private=True)
    with pytest.raises(ValueError):
        check_base_url("http://u:p@host.docker.internal:11434/v1", allow_private=False)


@pytest.mark.parametrize(
    ("configured", "url", "other_port"),
    [
        ("http://ollama/v1", "http://ollama:80/v1", "http://ollama:8080/v1"),
        ("http://ollama:80/v1", "http://ollama/v1", "http://ollama:8080/v1"),
        (
            "https://ollama.internal/v1",
            "https://ollama.internal:443/v1",
            "https://ollama.internal:8443/v1",
        ),
    ],
)
def test_default_ports_compare_equal(
    monkeypatch: pytest.MonkeyPatch, configured: str, url: str, other_port: str
) -> None:
    """An implicit and an explicit default port name the same server; another port does not."""
    monkeypatch.setenv("OLLAMA_BASE_URL", configured)
    assert is_operator_ollama(url)
    assert not is_operator_ollama(other_port)


async def test_send_skips_the_public_only_path_for_the_configured_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator's server is reached directly; everything else still goes through
    ``safe_request`` (https, public address, pinned IP)."""
    calls: list[str] = []

    async def refuse(method: str, url: str, **_: Any) -> httpx.Response:
        calls.append(url)
        raise SSRFError("only https URLs are allowed")

    real_client = httpx.AsyncClient

    def mocked(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs.get("follow_redirects") is False
        transport = httpx.MockTransport(lambda _req: httpx.Response(200, json={"ok": True}))
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(base, "safe_request", refuse)
    monkeypatch.setattr(httpx, "AsyncClient", mocked)
    with pytest.raises(base.AgentLLMError, match="not allowed"):
        await base.post_json(None, f"{HOST}/embeddings", {}, {}, timeout_s=5, api_key=None)
    assert calls == [f"{HOST}/embeddings"]

    monkeypatch.setenv("OLLAMA_BASE_URL", HOST)
    data, _ = await base.post_json(None, f"{HOST}/embeddings", {}, {}, timeout_s=5, api_key=None)
    assert data == {"ok": True} and len(calls) == 1
    other = "http://host.docker.internal:9999/v1/embeddings"
    with pytest.raises(base.AgentLLMError, match="not allowed"):
        await base.post_json(None, other, {}, {}, timeout_s=5, api_key=None)
    assert calls[-1] == other
