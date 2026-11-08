from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pareeksha.agent_llm.base import AgentLLMError
from pareeksha.rag import embeddings
from pareeksha.rag.embeddings import build_embedder
from pareeksha.schemas.rag import EmbeddingConfig

KEY = "sk-secret-key-123"


def _client(handler: Any, seen: list[httpx.Request]) -> httpx.AsyncClient:
    def wrap(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=handler(req, json.loads(req.content)))

    return httpx.AsyncClient(transport=httpx.MockTransport(wrap))


def _openai_reply(_: httpx.Request, body: dict[str, Any]) -> dict[str, Any]:
    n = len(body["input"])
    # Out of order on purpose: vectors must come back sorted by index.
    data = [{"index": i, "embedding": [float(i)]} for i in reversed(range(n))]
    return {"data": data, "usage": {"prompt_tokens": 7}}


@pytest.mark.parametrize(
    ("provider", "url_prefix"),
    [
        ("openai", "https://api.openai.com/v1/embeddings"),
        ("mistral", "https://api.mistral.ai/v1/embeddings"),
        ("jina", "https://api.jina.ai/v1/embeddings"),
        ("ollama", "http://localhost:11434/v1/embeddings"),
    ],
)
async def test_openai_wire_families(provider: str, url_prefix: str) -> None:
    seen: list[httpx.Request] = []
    cfg = EmbeddingConfig(provider=provider, model="m", dimensions=256)  # type: ignore[arg-type]
    emb = build_embedder(cfg, api_key=KEY, http=_client(_openai_reply, seen))
    res = await emb.embed(["a", "b", "c"], kind="document")
    assert res.vectors == [[0.0], [1.0], [2.0]]
    assert res.input_tokens == 7
    assert str(seen[0].url) == url_prefix
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(seen[0].content)
    assert body == {"model": "m", "input": ["a", "b", "c"], "dimensions": 256}


async def test_openai_compatible_needs_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        build_embedder(EmbeddingConfig(provider="openai_compatible", model="m"), api_key=None)
    seen: list[httpx.Request] = []
    cfg = EmbeddingConfig(provider="openai_compatible", model="m", base_url="https://h.example/v1/")
    await build_embedder(cfg, api_key=None, http=_client(_openai_reply, seen)).embed(
        ["a"], kind="query"
    )
    assert str(seen[0].url) == "https://h.example/v1/embeddings"
    assert "authorization" not in seen[0].headers


@pytest.mark.parametrize("kind", ["query", "document"])
async def test_voyage(kind: str) -> None:
    seen: list[httpx.Request] = []
    emb = build_embedder(
        EmbeddingConfig(provider="voyage", model="voyage-3"),
        api_key=KEY,
        http=_client(_openai_reply, seen),
    )
    await emb.embed(["a"], kind=kind)  # type: ignore[arg-type]
    assert str(seen[0].url) == "https://api.voyageai.com/v1/embeddings"
    assert json.loads(seen[0].content)["input_type"] == kind


@pytest.mark.parametrize(
    ("kind", "expected"), [("query", "search_query"), ("document", "search_document")]
)
async def test_cohere(kind: str, expected: str) -> None:
    seen: list[httpx.Request] = []

    def reply(_: httpx.Request, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "embeddings": {"float": [[1.0, 2.0] for _ in body["texts"]]},
            "meta": {"billed_units": {"input_tokens": 5}},
        }

    emb = build_embedder(
        EmbeddingConfig(provider="cohere", model="embed-v4.0"),
        api_key=KEY,
        http=_client(reply, seen),
    )
    res = await emb.embed(["a", "b"], kind=kind)  # type: ignore[arg-type]
    assert res.vectors == [[1.0, 2.0], [1.0, 2.0]]
    assert res.input_tokens == 5
    assert str(seen[0].url) == "https://api.cohere.com/v2/embed"
    body = json.loads(seen[0].content)
    assert body["input_type"] == expected
    assert body["embedding_types"] == ["float"]
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


async def test_gemini() -> None:
    seen: list[httpx.Request] = []

    def reply(_: httpx.Request, body: dict[str, Any]) -> dict[str, Any]:
        return {"embeddings": [{"values": [float(i)]} for i, _ in enumerate(body["requests"])]}

    emb = build_embedder(
        EmbeddingConfig(provider="gemini", model="text-embedding-004"),
        api_key=KEY,
        http=_client(reply, seen),
    )
    res = await emb.embed(["a", "b"], kind="query")
    assert res.vectors == [[0.0], [1.0]]
    assert str(seen[0].url).endswith("/v1beta/models/text-embedding-004:batchEmbedContents")
    assert seen[0].headers["x-goog-api-key"] == KEY
    reqs = json.loads(seen[0].content)["requests"]
    assert reqs[0]["taskType"] == "RETRIEVAL_QUERY"
    assert reqs[0]["model"] == "models/text-embedding-004"
    assert reqs[1]["content"] == {"parts": [{"text": "b"}]}
    await emb.embed(["a"], kind="document")
    assert json.loads(seen[1].content)["requests"][0]["taskType"] == "RETRIEVAL_DOCUMENT"


async def test_azure_openai() -> None:
    seen: list[httpx.Request] = []
    cfg = EmbeddingConfig(
        provider="azure_openai",
        model="ignored",
        base_url="https://r.openai.azure.com/openai/deployments/d",
    )
    await build_embedder(cfg, api_key=KEY, http=_client(_openai_reply, seen)).embed(
        ["a"], kind="document"
    )
    assert (
        str(seen[0].url)
        == "https://r.openai.azure.com/openai/deployments/d/embeddings?api-version=2024-10-21"
    )
    assert seen[0].headers["api-key"] == KEY
    assert "authorization" not in seen[0].headers


async def test_bedrock_titan_one_call_per_text() -> None:
    seen: list[httpx.Request] = []

    def reply(_: httpx.Request, body: dict[str, Any]) -> dict[str, Any]:
        return {"embedding": [float(len(body["inputText"]))], "inputTextTokenCount": 3}

    cfg = EmbeddingConfig(
        provider="bedrock",
        model="amazon.titan-embed-text-v2:0",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
    )
    res = await build_embedder(cfg, api_key=KEY, http=_client(reply, seen)).embed(
        ["a", "bb"], kind="document"
    )
    assert res.vectors == [[1.0], [2.0]]
    assert res.input_tokens == 6
    assert len(seen) == 2
    assert seen[0].url.raw_path == b"/model/amazon.titan-embed-text-v2%3A0/invoke"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


async def test_bedrock_cohere_model() -> None:
    seen: list[httpx.Request] = []

    def reply(_: httpx.Request, body: dict[str, Any]) -> dict[str, Any]:
        return {"embeddings": [[1.0] for _ in body["texts"]]}

    cfg = EmbeddingConfig(
        provider="bedrock",
        model="cohere.embed-multilingual-v3",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
    )
    res = await build_embedder(cfg, api_key=KEY, http=_client(reply, seen)).embed(
        ["a", "b"], kind="query"
    )
    assert res.vectors == [[1.0], [1.0]]
    assert len(seen) == 1
    assert json.loads(seen[0].content) == {"texts": ["a", "b"], "input_type": "search_query"}


async def test_batches_of_64() -> None:
    seen: list[httpx.Request] = []
    emb = build_embedder(
        EmbeddingConfig(provider="openai", model="m"),
        api_key=KEY,
        http=_client(_openai_reply, seen),
    )
    res = await emb.embed([str(i) for i in range(130)], kind="document")
    assert [len(json.loads(r.content)["input"]) for r in seen] == [64, 64, 2]
    assert len(res.vectors) == 130


async def test_error_never_contains_key() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": f"bad key {KEY}"}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(boom))
    emb = build_embedder(EmbeddingConfig(provider="openai", model="m"), api_key=KEY, http=http)
    with pytest.raises(AgentLLMError) as exc:
        await emb.embed(["a"], kind="query")
    assert KEY not in str(exc.value)
    assert exc.value.status == 401


async def test_malformed_response_is_agent_llm_error() -> None:
    emb = build_embedder(
        EmbeddingConfig(provider="openai", model="m"),
        api_key=KEY,
        http=_client(lambda *_: {"nope": 1}, []),
    )
    with pytest.raises(AgentLLMError):
        await emb.embed(["a"], kind="query")


async def test_local_embedder_uses_query_and_passage(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[tuple[str, str]] = []

    class FakeTextEmbedding:
        def __init__(self, name: str, cache_dir: str):
            created.append((name, cache_dir))

        def query_embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0] for _ in texts]

        def passage_embed(self, texts: list[str]) -> list[list[float]]:
            return [[2.0] for _ in texts]

    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", FakeTextEmbedding)
    monkeypatch.setattr(embeddings, "_MODELS", {})
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", "/tmp/models")
    emb = build_embedder(EmbeddingConfig(), api_key=None)
    q = await emb.embed(["abcdefgh"], kind="query")
    d = await emb.embed(["x", "y"], kind="document")
    assert q.vectors == [[1.0]]
    assert q.input_tokens == 2
    assert d.vectors == [[2.0], [2.0]]
    assert len(created) == 1  # singleton per model name
    assert created[0][1] == "/tmp/models"
