"""Retriever review fixes: zero-score BM25 hits, recorded timings, rerank tokens, cold loads."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from pareeksha.rag.embeddings import EmbedResult
from pareeksha.rag.retriever import Retriever
from tests.unit.rag.test_retriever import FakeChat, FakeEmbedder, FakeReranker, cfg, make_index


def retriever(embedder: Any = None, reranker: Any = None, **kw: Any) -> Retriever:
    return Retriever(
        cfg(**kw), make_index(), embedder or FakeEmbedder(), reranker or FakeReranker(), model="m"
    )


async def test_bm25_returns_only_chunks_that_share_a_term() -> None:
    out = await retriever(method="bm25", top_k=3).retrieve("kyc", chat=None)
    assert [r["text"] for r in out.results] == ["Loans need KYC."]  # not padded to top_k with zeros
    none = await retriever(method="bm25", top_k=3).retrieve("zzz", chat=None)
    assert none.results == [] and none.context == ""


async def test_multi_query_fusion_gets_no_points_for_unmatched_chunks() -> None:
    chat = FakeChat('["emi"]')  # rewrite; the original query is "kyc"
    out = await retriever(method="bm25", query_transform="multi_query", top_k=3).retrieve(
        "kyc", chat=chat
    )
    assert {r["text"] for r in out.results} == {"Loans need KYC.", "EMI is due monthly."}


async def test_hybrid_does_not_promote_zero_score_bm25_chunks() -> None:
    """bm25 matches only "Loans need KYC."; dense prefers the refund chunk (axis 0 ties)."""

    class Axis0(FakeEmbedder):
        async def embed(self, texts: Sequence[str], *, kind: Any) -> EmbedResult:
            return EmbedResult([[1.0, 0.0, 0.0] for _ in texts], 1, 1)

    out = await retriever(Axis0(), method="hybrid", top_k=3, rrf_k=1).retrieve("kyc", chat=None)
    # with padding the two non-matching chunks would collect bm25 points too (1/(1+2), 1/(1+3));
    # without it the matching chunk is first (bm25 rank 1 + dense rank 3) and the rest follow
    assert out.results[0]["text"] == "Loans need KYC."


async def test_every_stage_is_timed() -> None:
    chat = FakeChat('["emi"]')
    out = await retriever(method="hybrid_rerank", query_transform="multi_query").retrieve(
        "kyc", chat=chat
    )
    t = out.timings
    assert {"rewrite_ms", "embed_ms", "search_ms", "rerank_ms", "total_ms"} <= set(t)
    assert t["embed_ms"] == 1 and t["rerank_ms"] == 2  # the providers' own latencies
    assert t["total_ms"] == t["rewrite_ms"] + t["embed_ms"] + t["search_ms"] + t["rerank_ms"]


async def test_cold_model_load_is_not_retrieval_latency() -> None:
    class SlowLoad(FakeEmbedder):
        async def embed(self, texts: Sequence[str], *, kind: Any) -> EmbedResult:
            await asyncio.sleep(0.2)  # model load; the embedder reports inference time only
            return EmbedResult([[1.0, 0.0, 0.0] for _ in texts], 1, 4)

    out = await retriever(SlowLoad(), method="dense").retrieve("refund", chat=None)
    assert out.timings["embed_ms"] == 4
    assert out.timings["total_ms"] < 100


async def test_hosted_reranker_records_rerank_tokens() -> None:
    query = "loan refund emi"
    hosted = await retriever(method="hybrid_rerank", reranker_provider="cohere").retrieve(
        query, chat=None
    )
    docs = ["Refunds take seven days.", "Loans need KYC.", "EMI is due monthly."]
    expected = len(docs) * (len(query) // 4) + sum(len(d) for d in docs) // 4
    assert hosted.usage["rerank_tokens"] == expected > 0
    local = await retriever(method="hybrid_rerank", reranker_provider="local").retrieve(
        query, chat=None
    )
    assert local.usage["rerank_tokens"] == 0
    other = await retriever(method="hybrid").retrieve(query, chat=None)
    assert "rerank_tokens" not in other.usage
