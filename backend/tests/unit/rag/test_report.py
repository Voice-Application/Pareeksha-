"""RAG report math on plain rows (no DB)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from pareeksha.rag.report import (
    CallData,
    EntryModels,
    Prices,
    conversation_cost,
    finish,
    percentile,
    recommend,
    summarize,
    wilson,
)


def test_wilson() -> None:
    lo, hi = wilson(7, 10) or (0, 0)
    assert lo == pytest.approx(0.397, abs=0.002) and hi == pytest.approx(0.892, abs=0.002)
    assert wilson(0, 0) is None
    lo0, hi0 = wilson(0, 5) or (1, 0)
    assert lo0 == 0.0 and 0.4 < hi0 < 0.5
    assert (wilson(10, 10) or (0, 0))[1] == 1.0


def test_percentile() -> None:
    assert percentile([], 50) is None
    assert percentile([5], 95) == 5
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([0, 100], 95) == 95


def _call(
    hit: bool | None = None,
    faith: float | None = None,
    halluc: bool | None = None,
    in_tok: int = 0,
    out_tok: int = 0,
    embed: int = 0,
    total_ms: int | None = None,
    skipped: list[dict[str, Any]] | None = None,
) -> CallData:
    m: dict[str, Any] = {}
    if hit is not None:
        m.update(hit_at_k=hit, reciprocal_rank=1.0 if hit else 0.0, context_precision=0.5)
    if faith is not None:
        m["faithfulness"] = faith
    if halluc is not None:
        m["hallucinated"] = halluc
    return CallData(
        metrics=m,
        skipped=skipped or [],
        retrievals=[{"timings": {"total_ms": total_ms}, "usage": {"embed_tokens": embed}}]
        if total_ms is not None
        else [],
        events=[
            {
                "type": "agent_llm_usage",
                "data": {"input_tokens": in_tok, "output_tokens": out_tok},
            }
        ],
        agent_turn_ms=[100, 300],
    )


PRICES: Prices = {("llm", "openai", "m"): (Decimal(100), Decimal(400))}
LLM = ("openai", "m")


def _sum(label: str, kind: str, calls: list[CallData], prices: Prices = PRICES) -> Any:
    models = EntryModels(llm=LLM, embedding=("local", "e") if kind == "rag" else None)
    return summarize(
        label, kind, calls, run_id=None, run_status="completed", prices=prices, models=models
    )


def test_cost_null_when_unpriced_and_local_free() -> None:
    tokens = {"agent_input": 1000, "agent_output": 100, "query_embedding": 50, "rerank": 0}
    m = EntryModels(llm=LLM, embedding=("local", "e"))
    # 1000*100/1e6 + 100*400/1e6 = 0.14; local embedding is 0
    assert conversation_cost(tokens, PRICES, m) == Decimal("0.14")
    assert conversation_cost(tokens, {}, m) is None
    hosted = EntryModels(llm=LLM, embedding=("openai", "emb"))
    assert conversation_cost(tokens, PRICES, hosted) is None
    assert conversation_cost({**tokens, "query_embedding": 0}, PRICES, hosted) == Decimal("0.14")


def test_savings_and_row_stats() -> None:
    fc = _sum("Full context", "full_context", [_call(in_tok=10_000, out_tok=100)] * 2)
    rag = _sum(
        "r",
        "rag",
        [
            _call(
                hit=True, faith=1.0, halluc=False, in_tok=1000, out_tok=100, embed=20, total_ms=40
            ),
            _call(
                hit=False, faith=0.5, halluc=True, in_tok=1000, out_tok=100, embed=20, total_ms=80
            ),
        ],
    )
    rows, rec = finish([fc, rag], monthly=10_000)
    r = rows[1]
    assert r["n_calls"] == 2 and r["n_questions_with_truth"] == 2
    assert r["retrieval"]["hit_rate"] == 0.5 and r["retrieval"]["mrr"] == 0.5
    assert r["generation"]["hallucination_rate"] == 0.5
    assert r["generation"]["faithfulness"] == 0.75
    assert r["latency_ms"]["retrieval_p50"] == 60 and r["latency_ms"]["turn_p50"] == 200
    assert r["tokens_per_conversation"]["query_embedding"] == 20
    # fc cost 1.04/conv, rag 0.14/conv -> saves 0.90/conv = 9_000/month, 86.5%
    assert rows[0]["cost_per_conversation_inr"] == 1.04 and r["cost_per_conversation_inr"] == 0.14
    assert r["savings_vs_full_context"] == {"inr": 9000.0, "pct": 86.5}
    assert r["savings_vs_no_rag"] is None and rows[0]["savings_vs_full_context"] is None
    assert r["monthly_cost_inr"] == 1400.0
    assert r["token_savings_vs_full_context_pct"] == 88.9  # 1120 vs 10100 tokens
    assert rec["label"] is None and "(2 < 10)" in rec["reason"]


def test_token_savings_without_prices() -> None:
    fc = _sum("fc", "full_context", [_call(in_tok=1000)], prices={})
    rag = _sum("r", "rag", [_call(in_tok=250)], prices={})
    rows, _ = finish([fc, rag], monthly=100)
    assert rows[1]["cost_per_conversation_inr"] is None
    assert rows[1]["savings_vs_full_context"] is None
    assert rows[1]["token_savings_vs_full_context_pct"] == 75.0


def test_skipped_counts_and_empty_row() -> None:
    s = _sum("r", "rag", [_call(skipped=[{"metric": "faithfulness", "reason": "local_only"}] * 2)])
    assert s.row["generation"]["skipped"] == {"local_only": 2}
    empty = _sum("na", "full_context", [])
    assert empty.row["n_calls"] == 0 and empty.cost is None


def _cand(
    label: str, n: int, hit: float | None, faith: float | None, cost: str | None, ms: float
) -> Any:
    return {
        "label": label,
        "kind": "rag",
        "n": n,
        "hit_rate": hit,
        "faithfulness": faith,
        "cost": None if cost is None else Decimal(cost),
        "retrieval_p50": ms,
    }


def test_recommendation_rule() -> None:
    few = recommend([_cand("a", 9, 1.0, 1.0, "1", 1)])
    assert few == {"label": None, "reason": "not enough ground-truth questions (9 < 10)"}
    low = recommend([_cand("a", 20, 0.6, 1.0, "1", 1)])
    assert low == {"label": None, "reason": "no config reached 70% hit rate"}
    # baselines are never recommended
    base = {**_cand("full", 50, 1.0, 1.0, "0", 1), "kind": "full_context"}
    assert recommend([base])["label"] is None
    rows = [
        _cand("small", 5, 1.0, 1.0, "0", 1),  # too few questions
        _cand("weak", 20, 0.5, 1.0, "0", 1),  # hit rate too low
        _cand("faithful", 20, 0.8, 0.9, "5", 90),
        _cand("cheap", 20, 0.8, 0.8, "1", 10),
    ]
    assert recommend(rows)["label"] == "faithful"
    tie = [
        _cand("pricey", 20, 0.8, 0.9, "5", 10),
        _cand("cheaper", 20, 0.8, 0.9, "2", 90),
        _cand("unpriced", 20, 0.8, 0.9, None, 1),
    ]
    assert recommend(tie)["label"] == "cheaper"
    tie2 = [_cand("slow", 20, 0.8, 0.9, "2", 90), _cand("fast", 20, 0.8, 0.9, "2", 10)]
    assert recommend(tie2)["label"] == "fast"
