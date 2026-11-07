"""A turn whose retrieval failed has no retrievals row: that is a miss, never skipped."""

from __future__ import annotations

from pareeksha.rag.metrics import compute_rag_metrics
from tests.unit.evaluation.fakes import ScriptedProvider, client_for
from tests.unit.rag.test_metrics import CALL, DOC, inputs, judge, res


async def test_failed_first_turn_retrieval_is_a_miss_not_the_next_turns_hit() -> None:
    later_hit = {"turn_idx": 3, "results": [res(DOC, 150, 250)]}
    inp = inputs(retrievals=[later_hit], failed_turns=[1])  # turn 1 failed: no row
    r = await compute_rag_metrics(CALL, inp, client_for(ScriptedProvider([judge([])])))
    assert r.metrics["hit_at_k"] is False and r.metrics["reciprocal_rank"] == 0.0
    assert r.metrics["context_precision"] == 0.0
    assert {"metric": "hit_at_k", "reason": "no_ground_truth"} not in r.skipped


async def test_every_retrieval_failed_is_a_miss() -> None:
    inp = inputs(retrievals=[], failed_turns=[1, 3])
    r = await compute_rag_metrics(CALL, inp, client_for(ScriptedProvider([judge([])])))
    assert r.metrics["hit_at_k"] is False and r.metrics["reciprocal_rank"] == 0.0


async def test_answer_turn_retrieval_is_still_graded() -> None:
    inp = inputs(
        retrievals=[
            {"turn_idx": 1, "results": [res(DOC, 150, 250)]},
            {"turn_idx": 3, "results": []},
        ],
        failed_turns=[3],
    )
    r = await compute_rag_metrics(CALL, inp, client_for(ScriptedProvider([judge([])])))
    assert r.metrics["hit_at_k"] is True and r.metrics["reciprocal_rank"] == 1.0


async def test_without_ground_truth_nothing_is_counted() -> None:
    inp = inputs(retrievals=[], failed_turns=[1], expectation=None)
    r = await compute_rag_metrics(CALL, inp, client_for(ScriptedProvider([judge([])])))
    assert "hit_at_k" not in r.metrics
    assert {"metric": "hit_at_k", "reason": "no_ground_truth"} in r.skipped
