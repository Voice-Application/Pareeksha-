"""Retriever with a fake embedder, reranker and chat over an in-memory index."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from pareeksha.agent_llm.base import AgentMessage, ChatReply, ToolSpec
from pareeksha.rag.embeddings import EmbedResult
from pareeksha.rag.retriever import (
    LoadedIndex,
    Retriever,
    build_loaded_index,
    get_or_load,
    parse_rewrites,
)
from pareeksha.schemas.rag import RagConfig

DOC = "Refunds take seven days. Loans need KYC. EMI is due monthly."
DOC_ID = uuid.uuid4()
# axis 0 = refund, 1 = loan, 2 = emi
TEXTS = [
    ("Refunds take seven days.", [1.0, 0.0, 0.0], (0, 24)),
    ("Loans need KYC.", [0.0, 1.0, 0.0], (25, 40)),
    ("EMI is due monthly.", [0.0, 0.0, 1.0], (41, 60)),
]


def make_index() -> LoadedIndex:
    chunks = [
        {
            "id": uuid.uuid4(),
            "document_id": DOC_ID,
            "filename": "faq.txt",
            "text": t,
            "start_char": s,
            "end_char": e,
            "parent_start": 0,
            "parent_end": len(DOC),
            "embedding": v,
        }
        for t, v, (s, e) in TEXTS
    ]
    return build_loaded_index(chunks, {str(DOC_ID): DOC})


def vec(text: str) -> list[float]:
    low = text.lower()
    v = [float("refund" in low), float("loan" in low), float("emi" in low)]
    return v if any(v) else [0.1, 0.1, 0.1]


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: Sequence[str], *, kind: Any) -> EmbedResult:
        self.calls.append(list(texts))
        return EmbedResult([vec(t) for t in texts], 3 * len(texts), 1)


class FakeReranker:
    """Prefers the shortest document."""

    async def rerank(self, query: str, docs: Sequence[str]) -> tuple[list[float], int]:
        return [1.0 / len(d) for d in docs], 2


class FakeChat:
    def __init__(self, text: str) -> None:
        self.text, self.seen = text, []  # type: ignore[var-annotated]

    async def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        model: str,
        temperature: float,
        timeout_s: float = 60.0,
    ) -> ChatReply:
        self.seen.append(list(messages))
        return ChatReply(self.text, (), 11, 5, 3)


def cfg(**kw: Any) -> RagConfig:
    return RagConfig.model_validate({"kb_id": uuid.uuid4(), "top_k": 1, "candidate_k": 3, **kw})


def retriever(
    index: LoadedIndex | None = None, embedder: FakeEmbedder | None = None, **kw: Any
) -> Retriever:
    return Retriever(
        cfg(**kw), index or make_index(), embedder or FakeEmbedder(), FakeReranker(), model="m"
    )


async def test_bm25() -> None:
    out = await retriever(method="bm25").retrieve("when is emi due", chat=None)
    assert out.results[0]["text"] == "EMI is due monthly."
    assert out.context == "[1] (source: faq.txt)\nEMI is due monthly."


async def test_dense() -> None:
    emb = FakeEmbedder()
    out = await retriever(embedder=emb, method="dense").retrieve("refund please", chat=None)
    assert out.results[0]["text"].startswith("Refunds")
    assert out.usage["embed_tokens"] == 3


async def test_hybrid() -> None:
    out = await retriever(method="hybrid").retrieve("need a loan", chat=None)
    assert out.results[0]["text"] == "Loans need KYC."


async def test_hybrid_rerank_uses_reranker() -> None:
    out = await retriever(method="hybrid_rerank", top_k=1).retrieve("loan refund emi", chat=None)
    assert out.results[0]["text"] == "Loans need KYC."  # shortest of the candidates
    assert "rerank_ms" in out.timings


async def test_mmr() -> None:
    out = await retriever(method="mmr", top_k=2, candidate_k=3).retrieve("loan", chat=None)
    assert len(out.results) == 2 and out.results[0]["text"] == "Loans need KYC."


async def test_multi_query_fuses() -> None:
    chat = FakeChat('```json\n["refund policy", "emi date"]\n```')
    out = await retriever(method="dense", query_transform="multi_query", top_k=3).retrieve(
        "loan", chat=chat
    )
    assert out.queries == ["loan", "refund policy", "emi date"]
    assert {r["text"] for r in out.results} == {t for t, _, _ in TEXTS}
    assert out.usage["transform_input_tokens"] == 11


async def test_multi_query_bad_json_falls_back() -> None:
    out = await retriever(method="dense", query_transform="multi_query").retrieve(
        "loan", chat=FakeChat("not json")
    )
    assert out.queries == ["loan"] and out.warnings == ["query_transform_failed"]
    assert out.results[0]["text"] == "Loans need KYC."


async def test_hyde_embeds_hypothetical() -> None:
    emb = FakeEmbedder()
    chat = FakeChat("The refund arrives in a week.")
    out = await retriever(embedder=emb, method="dense", query_transform="hyde").retrieve(
        "when do I get money back", chat=chat
    )
    assert emb.calls == [["The refund arrives in a week."]]
    assert out.queries == ["when do I get money back"]
    assert out.results[0]["text"].startswith("Refunds")


async def test_small_to_big_returns_parent_text() -> None:
    out = await retriever(method="dense", small_to_big=True, top_k=3).retrieve("loan", chat=None)
    assert out.context == f"[1] (source: faq.txt)\n{DOC}"  # three chunks, one parent
    assert len(out.results) == 3


async def test_index_cache_loads_once() -> None:
    calls = 0

    async def loader() -> LoadedIndex:
        nonlocal calls
        calls += 1
        return make_index()

    key = f"cache-{uuid.uuid4()}"
    first = await get_or_load(key, loader)
    assert await get_or_load(key, loader) is first
    assert calls == 1


def test_parse_rewrites() -> None:
    assert parse_rewrites('["a", " b ", 3, ""]') == ["a", "b"]
