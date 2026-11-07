"""RAG report math over plain rows: no DB, no I/O (plans/2026-11-07-rag-lab.md, Task 9).

Money is ``Decimal`` internally; prices are per 1M tokens in INR. Local embedding/reranker
providers cost 0. A model without a price makes the cost ``None`` (tokens are still reported).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

MIN_QUESTIONS = 10
MIN_HIT_RATE = 0.7
_M = Decimal(1_000_000)

#: (kind, provider, model) -> (input_per_m, output_per_m or None)
Prices = dict[tuple[str, str, str], tuple[Decimal, Decimal | None]]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval (95% by default); ``None`` when n is 0."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolated percentile (p in 0..100); ``None`` for no values."""
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * p / 100
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def money(d: Decimal | None) -> float | None:
    return None if d is None else float(round(d, 2))


def price_of(
    prices: Prices, kind: str, provider: str, model: str
) -> tuple[Decimal, Decimal | None] | None:
    if kind != "llm" and provider == "local":
        return Decimal(0), Decimal(0)
    return prices.get((kind, provider, model))


@dataclass
class CallData:
    """What the report needs from one call."""

    metrics: dict[str, Any] = field(default_factory=dict)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    retrievals: list[dict[str, Any]] = field(default_factory=list)  # {"timings", "usage"}
    events: list[dict[str, Any]] = field(default_factory=list)  # call.event_log
    agent_turn_ms: list[int] = field(default_factory=list)


@dataclass
class EntryModels:
    """Which price to use for each token kind of an entry (``None`` = nothing of that kind)."""

    llm: tuple[str, str] | None = None
    embedding: tuple[str, str] | None = None
    rerank: tuple[str, str] | None = None


@dataclass
class Summary:
    row: dict[str, Any]
    cost: Decimal | None
    tokens: float


def _tokens(calls: Sequence[CallData]) -> dict[str, int]:
    t = {"agent_input": 0, "agent_output": 0, "query_embedding": 0, "rerank": 0}
    for c in calls:
        for e in c.events:
            if e.get("type") == "agent_llm_usage":
                d = e.get("data") or {}
                if d.get("purpose") == "tool_simulation":  # test scaffolding, no production cost
                    continue
                t["agent_input"] += int(d.get("input_tokens") or 0)
                t["agent_output"] += int(d.get("output_tokens") or 0)
        for r in c.retrievals:
            u = r.get("usage") or {}
            t["query_embedding"] += int(u.get("embed_tokens") or 0)
            # multi-query / HyDE rewrites are LLM calls on the agent model
            t["agent_input"] += int(u.get("transform_input_tokens") or 0)
            t["agent_output"] += int(u.get("transform_output_tokens") or 0)
            t["rerank"] += int(u.get("rerank_tokens") or 0)
    return t


def conversation_cost(
    tokens: Mapping[str, float], prices: Prices, models: EntryModels
) -> Decimal | None:
    """INR for these tokens; ``None`` if any component with tokens has no price."""
    total = Decimal(0)

    def add(amount: float, key: tuple[str, str] | None, kind: str, out: bool = False) -> bool:
        nonlocal total
        if not amount:
            return True
        p = price_of(prices, kind, *key) if key else None
        rate = None if p is None else (p[1] if out else p[0])
        if rate is None:
            return False
        total += Decimal(str(amount)) * rate / _M
        return True

    ok = (
        add(tokens["agent_input"], models.llm, "llm")
        and add(tokens["agent_output"], models.llm, "llm", out=True)
        and add(tokens["query_embedding"], models.embedding, "embedding")
        and add(tokens["rerank"], models.rerank, "rerank")
    )
    return total if ok else None


def summarize(
    label: str,
    kind: str,
    calls: Sequence[CallData],
    *,
    run_id: Any,
    run_status: str | None,
    prices: Prices,
    models: EntryModels,
    index_tokens: int = 0,
) -> Summary:
    n = len(calls)
    m = [c.metrics for c in calls]
    truth = [x for x in m if "hit_at_k" in x]
    hits = sum(1 for x in truth if x["hit_at_k"])
    judged = [x for x in m if "hallucinated" in x]
    halluc = sum(1 for x in judged if x["hallucinated"])

    def avg(key: str) -> float | None:
        return mean([float(x[key]) for x in m if key in x])

    def rate(key: str) -> float | None:
        return mean([1.0 if x[key] else 0.0 for x in m if key in x])

    skipped = Counter(str(s.get("reason")) for c in calls for s in c.skipped)
    rets = [r.get("timings") or {} for c in calls for r in c.retrievals]

    def col(key: str, src: list[dict[str, Any]] = rets) -> list[float]:
        return [float(t[key]) for t in src if t.get(key) is not None]

    turns = [float(x) for c in calls for x in c.agent_turn_ms]
    total = _tokens(calls)
    per = {k: (v / n if n else 0.0) for k, v in total.items()}
    cost = conversation_cost(per, prices, models) if n else None
    emb = price_of(prices, "embedding", *models.embedding) if models.embedding else None
    one_time = (
        Decimal(0)
        if models.embedding is None
        else None
        if emb is None
        else Decimal(index_tokens) * emb[0] / _M
    )
    row: dict[str, Any] = {
        "label": label,
        "kind": kind,
        "run_id": run_id,
        "run_status": run_status,
        "n_calls": n,
        "n_questions_with_truth": len(truth),
        "retrieval": {
            "hit_rate": hits / len(truth) if truth else None,
            "hit_rate_ci": wilson(hits, len(truth)),
            "mrr": avg("reciprocal_rank"),
            "context_precision": avg("context_precision"),
        },
        "generation": {
            "faithfulness": avg("faithfulness"),
            "n_judged": len(judged),
            "hallucination_rate": halluc / len(judged) if judged else None,
            "hallucination_ci": wilson(halluc, len(judged)),
            "answer_correct_rate": rate("answer_correct"),
            "refusal_correct_rate": rate("refusal_correct"),
            "skipped": dict(skipped),
        },
        "latency_ms": {
            "retrieval_p50": percentile(col("total_ms"), 50),
            "retrieval_p95": percentile(col("total_ms"), 95),
            "embed_p50": percentile(col("embed_ms"), 50),
            "search_p50": percentile(col("search_ms"), 50),
            "rerank_p50": percentile(col("rerank_ms"), 50),
            "rewrite_p50": percentile(col("rewrite_ms"), 50),
            "turn_p50": percentile(turns, 50),
            "turn_p95": percentile(turns, 95),
        },
        "tokens_per_conversation": per,
        "cost_per_conversation_inr": money(cost),
        "index_one_time": {"input_tokens": index_tokens, "cost_inr": money(one_time)},
    }
    return Summary(row, cost, sum(per.values()))


def _savings(base: Summary | None, s: Summary, monthly: int) -> dict[str, float] | None:
    if base is None or base is s or base.cost is None or s.cost is None or base.cost == 0:
        return None
    diff = base.cost - s.cost
    return {"inr": float(round(diff * monthly, 2)), "pct": float(round(diff / base.cost * 100, 1))}


def finish(
    summaries: Sequence[Summary], monthly: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Monthly cost, savings vs the baselines, and the recommendation."""
    fc = next((s for s in summaries if s.row["kind"] == "full_context" and s.row["n_calls"]), None)
    nr = next((s for s in summaries if s.row["kind"] == "no_rag" and s.row["n_calls"]), None)
    cands: list[dict[str, Any]] = []
    for s in summaries:
        r = s.row
        r["monthly_cost_inr"] = money(None if s.cost is None else s.cost * monthly)
        r["savings_vs_full_context"] = _savings(fc, s, monthly)
        r["savings_vs_no_rag"] = _savings(nr, s, monthly)
        r["token_savings_vs_full_context_pct"] = (
            round((fc.tokens - s.tokens) / fc.tokens * 100, 1)
            if fc is not None and fc is not s and fc.tokens and s.row["n_calls"]
            else None
        )
        cands.append(
            {
                "label": r["label"],
                "kind": r["kind"],
                "n": r["n_questions_with_truth"],
                "hit_rate": r["retrieval"]["hit_rate"],
                "faithfulness": r["generation"]["faithfulness"],
                "cost": s.cost,
                "retrieval_p50": r["latency_ms"]["retrieval_p50"],
            }
        )
    return [s.row for s in summaries], recommend(cands)


def recommend(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Among RAG configs with n >= 10 and hit rate >= 70%: best faithfulness, then cheapest,
    then fastest retrieval. Otherwise ``label`` is None and ``reason`` says why."""
    configs = [r for r in rows if r["kind"] == "rag"]
    big = [r for r in configs if r["n"] >= MIN_QUESTIONS]
    if not big:
        best_n = max((r["n"] for r in configs), default=0)
        return {
            "label": None,
            "reason": f"not enough ground-truth questions ({best_n} < {MIN_QUESTIONS})",
        }
    ok = [r for r in big if (r["hit_rate"] or 0) >= MIN_HIT_RATE]
    if not ok:
        return {"label": None, "reason": "no config reached 70% hit rate"}
    inf = Decimal("Infinity")
    win = min(
        ok,
        key=lambda r: (
            -(r["faithfulness"] if r["faithfulness"] is not None else -1.0),
            inf if r["cost"] is None else r["cost"],
            math.inf if r["retrieval_p50"] is None else r["retrieval_p50"],
        ),
    )
    return {
        "label": win["label"],
        "reason": (
            f"highest faithfulness among {len(ok)} config(s) with hit rate >= 70% "
            f"and at least {MIN_QUESTIONS} questions (n={win['n']}); ties go to lower cost, "
            "then faster retrieval"
        ),
    }
