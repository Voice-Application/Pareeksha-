from __future__ import annotations

import json
import uuid
from typing import Any

from pareeksha.rag.metrics import RagInputs, compute_rag_metrics, retrieval_metrics
from pareeksha.schemas.rag import RagExpectation
from tests.unit.evaluation.fakes import ScriptedProvider, client_for

DOC = uuid.uuid4()
CALL = uuid.uuid4()


def exp(**kw: Any) -> RagExpectation:
    base: dict[str, Any] = {"source_document_id": DOC, "source_span": (100, 200)}
    return RagExpectation(**{**base, **kw})


def res(doc: uuid.UUID, start: int, end: int) -> dict[str, Any]:
    return {"chunk_id": str(uuid.uuid4()), "document_id": str(doc), "start": start, "end": end}


def judge(claims: list[tuple[bool, int | None]], refused: bool = False, correct: Any = None) -> str:
    return json.dumps(
        {
            "claims": [{"text": "c", "supported": s, "evidence": e} for s, e in claims],
            "answer_correct": correct,
            "refused": refused,
        }
    )


def inputs(**kw: Any) -> RagInputs:
    base: dict[str, Any] = {
        "mode": "retrieval",
        "retrievals": [{"turn_idx": 1, "results": [res(DOC, 0, 50), res(DOC, 150, 250)]}],
        "expectation": exp(),
        "agent_turns": ["The EMI is due on the 5th."],
        "context": ["chunk a", "chunk b"],
    }
    return RagInputs(**{**base, **kw})


def test_hit_and_reciprocal_rank() -> None:
    m = retrieval_metrics(inputs().retrievals[0]["results"], exp())
    assert m is not None
    assert m["hit_at_k"] is True and m["reciprocal_rank"] == 0.5
    miss = retrieval_metrics([res(DOC, 0, 100), res(uuid.uuid4(), 100, 200)], exp())
    assert miss == {"hit_at_k": False, "reciprocal_rank": 0.0, "context_precision": 0.0}


def test_context_precision() -> None:
    results = [res(DOC, 90, 110), res(DOC, 199, 300), res(DOC, 200, 300), res(DOC, 0, 10)]
    m = retrieval_metrics(results, exp())
    assert m is not None and m["context_precision"] == 0.5 and m["reciprocal_rank"] == 1.0


async def test_faithfulness_from_claims() -> None:
    p = ScriptedProvider([judge([(True, 0), (False, None), (True, 9), (True, 1)], correct=True)])
    inp = inputs(expectation=exp(reference_answer="5th"))
    r = await compute_rag_metrics(CALL, inp, client_for(p))
    # the claim citing a missing evidence block counts as unsupported
    assert r.metrics["claims_total"] == 4 and r.metrics["claims_supported"] == 2
    assert r.metrics["faithfulness"] == 0.5 and r.metrics["hallucinated"] is True
    assert r.metrics["answer_correct"] is True and r.metrics["hit_at_k"] is True
    assert "chunk a" in p.requests[0].messages[0].content
    assert r.skipped == []


async def test_no_claims_is_fully_faithful() -> None:
    r = await compute_rag_metrics(CALL, inputs(), client_for(ScriptedProvider([judge([])])))
    assert r.metrics["faithfulness"] == 1.0 and r.metrics["hallucinated"] is False


async def test_no_rag_hallucination_uses_source_text() -> None:
    inp = inputs(mode="off", retrievals=[], context=[], source_text="EMI is due on the 6th")
    p = ScriptedProvider([judge([(False, None)])])
    r = await compute_rag_metrics(CALL, inp, client_for(p))
    assert r.metrics["hallucinated"] is True
    assert "faithfulness" not in r.metrics and "hit_at_k" not in r.metrics
    assert "due on the 6th" in p.requests[0].messages[0].content


async def test_unanswerable_refusal_correct() -> None:
    e = RagExpectation(answerable=False, source_document_id=None, source_span=None)
    inp = inputs(expectation=e)
    ok = ScriptedProvider([judge([], refused=True)])
    r = await compute_rag_metrics(CALL, inp, client_for(ok))
    assert r.metrics["refusal_correct"] is True
    assert {"metric": "hit_at_k", "reason": "no_ground_truth"} in r.skipped
    bad = ScriptedProvider([judge([], refused=False)])
    r = await compute_rag_metrics(CALL, inp, client_for(bad))
    assert r.metrics["refusal_correct"] is False


async def test_local_only_skips_llm_metrics() -> None:
    p = ScriptedProvider([])
    inp = inputs(local_only=True, expectation=exp(reference_answer="x"))
    r = await compute_rag_metrics(CALL, inp, client_for(p))
    assert p.requests == [] and r.metrics["hit_at_k"] is True
    assert {s["reason"] for s in r.skipped} == {"local_only"}
    assert {s["metric"] for s in r.skipped} == {
        "hallucinated",
        "faithfulness",
        "refusal_correct",
        "answer_correct",
    }


async def test_no_evidence_skipped() -> None:
    p = ScriptedProvider([])
    inp = inputs(mode="off", retrievals=[], context=[], expectation=None)
    r = await compute_rag_metrics(CALL, inp, client_for(p))
    assert p.requests == [] and r.skipped == [{"metric": "hallucinated", "reason": "no_evidence"}]


async def test_judge_error_recorded_as_skipped() -> None:
    p = ScriptedProvider([RuntimeError("boom")] * 5)
    r = await compute_rag_metrics(CALL, inputs(), client_for(p))
    assert r.metrics["hit_at_k"] is True and "faithfulness" not in r.metrics
    assert {s["metric"] for s in r.skipped if s["reason"] == "judge_error"} == {
        "hallucinated",
        "faithfulness",
        "refusal_correct",
    }


async def test_evidence_capped() -> None:
    p = ScriptedProvider([judge([])])
    inp = inputs(context=["x" * 100_000, "y" * 100_000])
    r = await compute_rag_metrics(CALL, inp, client_for(p))
    assert r.metrics["evidence_truncated"] is True
    assert len(p.requests[0].messages[0].content) < 70_000
