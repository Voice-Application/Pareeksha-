from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pareeksha.agent_llm.base import AgentLLMError
from pareeksha.rag import rerank
from pareeksha.rag.rerank import build_reranker

KEY = "sk-secret-key-123"


def _client(reply: dict[str, Any], seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=reply)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# Results come back sorted by relevance, not in document order.
_ROWS = [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.5}]
_ROWS_FULL = [*_ROWS, {"index": 1, "relevance_score": 0.1}]


@pytest.mark.parametrize(
    ("provider", "url", "reply"),
    [
        ("cohere", "https://api.cohere.com/v2/rerank", {"results": _ROWS_FULL}),
        ("jina", "https://api.jina.ai/v1/rerank", {"results": _ROWS_FULL}),
        ("voyage", "https://api.voyageai.com/v1/rerank", {"data": _ROWS_FULL}),
    ],
)
async def test_hosted_rerank(provider: str, url: str, reply: dict[str, Any]) -> None:
    seen: list[httpx.Request] = []
    rr = build_reranker(provider, "rm", api_key=KEY, http=_client(reply, seen))
    scores, _ = await rr.rerank("q", ["a", "b", "c"])
    assert scores == [0.5, 0.1, 0.9]
    assert str(seen[0].url) == url
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(seen[0].content) == {
        "model": "rm",
        "query": "q",
        "documents": ["a", "b", "c"],
    }


async def test_partial_scores_rejected() -> None:
    rr = build_reranker("cohere", "rm", api_key=KEY, http=_client({"results": _ROWS}, []))
    with pytest.raises(AgentLLMError):
        await rr.rerank("q", ["a", "b", "c"])


async def test_empty_docs_makes_no_call() -> None:
    seen: list[httpx.Request] = []
    rr = build_reranker("cohere", "rm", api_key=KEY, http=_client({}, seen))
    assert await rr.rerank("q", []) == ([], 0)
    assert seen == []


async def test_local_reranker(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []

    class FakeTextCrossEncoder:
        def __init__(self, name: str, cache_dir: str):
            created.append(name)

        def rerank(self, query: str, docs: list[str]) -> list[float]:
            return [float(len(d)) for d in docs]

    import fastembed.rerank.cross_encoder as ce

    monkeypatch.setattr(ce, "TextCrossEncoder", FakeTextCrossEncoder)
    monkeypatch.setattr(rerank, "_ENCODERS", {})
    rr = build_reranker("local", "m", api_key=None)
    scores, _ = await rr.rerank("q", ["a", "bbb"])
    await rr.rerank("q", ["a"])
    assert scores == [1.0, 3.0]
    assert created == ["m"]


def test_unknown_provider() -> None:
    with pytest.raises(ValueError):
        build_reranker("nope", "m", api_key=None)
