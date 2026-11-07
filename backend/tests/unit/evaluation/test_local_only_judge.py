"""A call built on a local-only knowledge base never reaches the hosted rubric judge."""

from __future__ import annotations

import dataclasses

from pareeksha.evaluation.evaluator import evaluate_call
from tests.fixtures import synthetic_calls as sc
from tests.unit.evaluation.fakes import ScriptedProvider, client_for, judge_json


async def test_local_only_call_skips_the_judge() -> None:
    provider = ScriptedProvider([judge_json()])
    snap = dataclasses.replace(sc.wrong_amount_call(), local_only=True)
    record = await evaluate_call(snap, client_for(provider))
    assert provider.requests == []  # nothing was sent
    assert record.status == "judge_error" and record.needs_human_review
    assert record.review_reasons[0] == "local_only"
    assert record.overall_score is None and record.passed is None
    assert record.checks  # deterministic checks still ran locally


async def test_other_calls_are_still_judged() -> None:
    provider = ScriptedProvider([judge_json()])
    record = await evaluate_call(sc.wrong_amount_call(), client_for(provider))
    assert len(provider.requests) == 1 and record.status == "ok"
