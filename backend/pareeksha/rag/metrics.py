"""RAG metrics for one evaluated call: deterministic retrieval metrics plus LLM-judged generation
metrics (``rag_judge_v1``). Stored in ``rag_metrics``, outside the rubric, so judge calibration is
untouched. A judge failure is recorded as skipped and never fails the evaluation."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from pareeksha.llm.base import ChatMessage, LLMPurpose
from pareeksha.llm.client import LLMClient
from pareeksha.llm.prompts import prompt_hash, render_prompt
from pareeksha.rag.guard import platform_llm_may_see_kb
from pareeksha.schemas.rag import RagExpectation

log = logging.getLogger(__name__)

RAG_JUDGE_PROMPT = "rag_judge_v1"
#: Hard cap on evidence characters sent to the judge, trimmed per chunk.
EVIDENCE_CHAR_CAP = 60_000


class RagClaim(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    supported: bool
    evidence: int | None = None


class RagJudgeOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    claims: list[RagClaim]
    answer_correct: bool | None = None
    refused: bool


@dataclass(frozen=True)
class RagInputs:
    mode: str  # off | retrieval | full_context
    #: the call's retrievals by turn, each ``{"turn_idx": int, "results": [...]}``
    retrievals: list[dict[str, Any]] = field(default_factory=list)
    expectation: RagExpectation | None = None
    source_text: str | None = None  # document[span] of the expectation
    local_only: bool = False
    agent_turns: list[str] = field(default_factory=list)
    #: evidence texts the agent was shown (retrieved chunks or the live KB documents)
    context: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RagMetricsRecord:
    call_id: uuid.UUID
    metrics: dict[str, Any]
    skipped: list[dict[str, str]]


class RagStore(Protocol):
    async def load_rag_inputs(self, call_id: uuid.UUID) -> RagInputs | None: ...

    async def save_rag_metrics(self, call_id: uuid.UUID, record: RagMetricsRecord) -> None: ...


def _overlaps(r: dict[str, Any], doc_id: uuid.UUID | None, span: tuple[int, int]) -> bool:
    return (
        str(r.get("document_id")) == str(doc_id)
        and int(r.get("start_char", 0)) < span[1]
        and span[0] < int(r.get("end_char", 0))
    )


def retrieval_metrics(results: list[dict[str, Any]], exp: RagExpectation) -> dict[str, Any] | None:
    """Hit@k, reciprocal rank and context precision against the expected source span."""
    if exp.source_span is None:
        return None
    hits = [_overlaps(r, exp.source_document_id, exp.source_span) for r in results]
    first = next((i for i, h in enumerate(hits) if h), None)
    return {
        "hit_at_k": first is not None,
        "reciprocal_rank": 0.0 if first is None else 1 / (first + 1),
        "context_precision": sum(hits) / len(hits) if hits else 0.0,
    }


def cap_evidence(items: list[str], cap: int = EVIDENCE_CHAR_CAP) -> tuple[list[str], bool]:
    if sum(map(len, items)) <= cap:
        return items, False
    each = cap // len(items)
    return [i[:each] for i in items], True


def _judge_error(metrics: list[str]) -> list[dict[str, str]]:
    return [{"metric": m, "reason": "judge_error"} for m in metrics]


async def compute_rag_metrics(
    call_id: uuid.UUID, inp: RagInputs, client: LLMClient
) -> RagMetricsRecord:
    metrics: dict[str, Any] = {"mode": inp.mode}
    skipped: list[dict[str, str]] = []
    exp = inp.expectation

    # ---- retrieval (deterministic)
    if inp.mode == "retrieval":
        first = min(inp.retrievals, key=lambda r: r["turn_idx"], default=None)
        got = (
            retrieval_metrics(list(first["results"]) if first else [], exp)
            if exp is not None
            else None
        )
        if got is None:
            skipped += [
                {"metric": m, "reason": "no_ground_truth"}
                for m in ("hit_at_k", "reciprocal_rank", "context_precision")
            ]
        else:
            metrics.update(got)

    # ---- generation (LLM judge)
    wanted = ["hallucinated"]
    if inp.mode in ("retrieval", "full_context"):
        wanted.append("faithfulness")
    if exp is not None:
        wanted.append("refusal_correct")
        if exp.reference_answer:
            wanted.append("answer_correct")
        else:
            skipped.append({"metric": "answer_correct", "reason": "no_ground_truth"})

    if not platform_llm_may_see_kb(inp.local_only):
        skipped += [{"metric": m, "reason": "local_only"} for m in wanted]
        return RagMetricsRecord(call_id, metrics, skipped)

    evidence = [*inp.context, *([inp.source_text] if inp.source_text else [])]
    evidence = [e for e in evidence if e]
    judged = [m for m in wanted if m in ("refusal_correct", "answer_correct")]
    needs_evidence = [m for m in wanted if m in ("hallucinated", "faithfulness")]
    if not inp.agent_turns:
        skipped += [{"metric": m, "reason": "no_evidence"} for m in wanted]
        return RagMetricsRecord(call_id, metrics, skipped)
    if not evidence:
        skipped += [{"metric": m, "reason": "no_evidence"} for m in needs_evidence]
        needs_evidence = []
    if not (judged or needs_evidence):
        return RagMetricsRecord(call_id, metrics, skipped)

    evidence, truncated = cap_evidence(evidence)
    if truncated:
        metrics["evidence_truncated"] = True
    try:
        out = (
            await client.generate_json(
                purpose=LLMPurpose.JUDGE,
                messages=[
                    ChatMessage(
                        role="user",
                        content=render_prompt(
                            RAG_JUDGE_PROMPT,
                            evidence=evidence,
                            answer=inp.agent_turns,
                            reference_answer=exp.reference_answer if exp else "",
                        ),
                    )
                ],
                schema=RagJudgeOutput,
                prompt_hash=prompt_hash(RAG_JUDGE_PROMPT),
                temperature=0.0,
                thinking=False,
                timeout_s=120.0,
                repair_attempts=2,
            )
        ).parsed
    except Exception as exc:  # a RAG judge failure never fails the evaluation
        log.warning("rag judge failed for call %s: %s", call_id, exc)
        skipped += _judge_error(judged + needs_evidence)
        return RagMetricsRecord(call_id, metrics, skipped)

    if needs_evidence:
        # a "supported" claim must cite an evidence block that exists
        ok = [
            c.supported and c.evidence is not None and 0 <= c.evidence < len(evidence)
            for c in out.claims
        ]
        metrics["claims_total"] = len(ok)
        metrics["claims_supported"] = sum(ok)
        metrics["hallucinated"] = not all(ok)
        if "faithfulness" in needs_evidence:
            metrics["faithfulness"] = sum(ok) / len(ok) if ok else 1.0
    if "refusal_correct" in judged and exp is not None:
        metrics["refusal_correct"] = out.refused != exp.answerable
    if "answer_correct" in judged:
        if out.answer_correct is None:
            skipped += _judge_error(["answer_correct"])
        else:
            metrics["answer_correct"] = out.answer_correct
    return RagMetricsRecord(call_id, metrics, skipped)


async def evaluate_rag(store: RagStore, client: LLMClient, call_id: uuid.UUID) -> None:
    """Compute and upsert this call's ``rag_metrics`` row; no row for a call without RAG."""
    inp = await store.load_rag_inputs(call_id)
    if inp is None:
        return
    await store.save_rag_metrics(call_id, await compute_rag_metrics(call_id, inp, client))
