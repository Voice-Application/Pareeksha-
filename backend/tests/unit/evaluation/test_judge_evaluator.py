from __future__ import annotations

import dataclasses

import pytest

from pareeksha.evaluation.evaluator import CHECK_FAILURE_TYPES, evaluate_call, evaluation_id
from pareeksha.evaluation.judge import JudgeInput, render_judge_prompt
from pareeksha.evaluation.metrics import compute_metrics
from pareeksha.evaluation.types import Turn
from pareeksha.llm.base import LLMRetryableError
from pareeksha.llm.prompts import prompt_hash
from tests.fixtures import synthetic_calls as sc
from tests.unit.evaluation.fakes import ScriptedProvider, client_for, judge_json


def judge_input() -> JudgeInput:
    snap = sc.wrong_amount_call()
    return JudgeInput(
        agent=snap.agent,
        turns=snap.turns,
        metrics=compute_metrics(snap.turns),
        checks=[],
        call_language="hi-IN",
        scenario=snap.scenario,
        persona=snap.persona,
        tool_calls=snap.tool_calls or (),
    )


def test_prompt_contains_rubric_pieces_and_masks_pii() -> None:
    text = render_judge_prompt(judge_input())
    assert "Shree Finance EMI Reminder Bot" in text
    assert "This call is recorded" in text  # mandatory disclosure
    assert "we will send recovery agents" in text  # forbidden phrase
    assert '"emi_amount": 4200' in text  # fixtures as ground truth
    assert "3 | caller |" in text and "[PHONE]" in text
    assert "9876543210" not in text
    assert "record_ptp" in text and "task_completion (weight 25)" in text
    assert "Language: hi-IN · code-mix: heavy" in text


def test_prompt_for_recorded_call_without_scenario_or_persona() -> None:
    data = dataclasses.replace(judge_input(), scenario=None, persona=None, tool_calls=())
    text = render_judge_prompt(data)
    assert "Real recorded call" in text
    assert "Language: hi-IN · code-mix: unknown" in text
    assert "not available" in text


def test_prompt_marks_ground_truth_heard_text_and_barge_in() -> None:
    turn = Turn(
        0,
        "caller",
        0,
        900,
        text="x",
        text_masked="चार हज़ार",
        ground_truth_text="4000",
        agent_heard_text="40000",
        is_barge_in=True,
    )
    data = dataclasses.replace(judge_input(), turns=[turn])
    text = render_judge_prompt(data)
    assert "[said: 4000] [agent heard: 40000] [caller interrupted here]" in text


async def test_evaluate_call_scores_in_code_and_records_provenance() -> None:
    snap = sc.wrong_amount_call()
    provider = ScriptedProvider(
        [
            judge_json(
                (1, 1, 0, 3, 2, 3, 4), evidence=[2, 4], critical=True, failure_types=["wrong_fact"]
            )
        ]
    )
    rec = await evaluate_call(snap, client_for(provider))
    assert rec.status == "ok" and rec.overall_score == 40.0
    assert rec.critical_failure and rec.passed is False and rec.needs_human_review
    assert rec.review_reasons[0] == "critical_failure"
    assert "check_failed:amount_confirmed" in rec.review_reasons
    assert "check_failed:disclosure_present" in rec.review_reasons
    assert rec.failure_types[0] == "wrong_fact" and "missing_disclosure" in rec.failure_types
    assert rec.id == evaluation_id(snap.call_id) and rec.rubric_version == "rubric-2026-10-v1"
    assert rec.prompt_hash == "sha256:" + prompt_hash("judge_v1")
    assert rec.judge_model == "deepseek-v4-pro" and rec.temperature == 0.0
    assert (rec.input_tokens, rec.output_tokens) == (1000, 200)
    assert rec.est_cost == pytest.approx(0.0018)
    assert rec.raw_response is not None and rec.dimensions["factual_accuracy"]["score"] == 0
    assert len(rec.checks) >= 3 and rec.metrics.response_latency_count > 0
    req = provider.requests[0]
    assert req.temperature == 0.0 and not req.thinking and req.purpose.value == "judge"
    assert "9876543210" not in req.messages[0].content


async def test_clean_call_passes_without_review() -> None:
    provider = ScriptedProvider([judge_json((4, 4, 4, 3, 4, 4, 4), evidence=[2])])
    rec = await evaluate_call(sc.clean_call(), client_for(provider))
    assert rec.overall_score == 96.25 and rec.passed and not rec.needs_human_review
    assert rec.review_reasons == [] and rec.failure_types == []


async def test_invalid_evidence_triggers_repair_and_second_answer_is_used() -> None:
    provider = ScriptedProvider(
        [judge_json(evidence=[99]), judge_json(evidence=[1])],
    )
    rec = await evaluate_call(sc.clean_call(), client_for(provider))
    assert rec.status == "ok" and rec.dimensions["task_completion"]["evidence_turns"] == [1]
    assert "[99]" in provider.requests[1].messages[-1].content
    assert rec.input_tokens == 2000  # both calls billed


async def test_still_invalid_after_repair_is_stored_as_judge_error() -> None:
    provider = ScriptedProvider([judge_json(evidence=[99]), judge_json(evidence=[77])])
    rec = await evaluate_call(sc.clean_call(), client_for(provider))
    assert rec.status == "judge_error" and rec.overall_score is None and rec.passed is None
    assert rec.needs_human_review and rec.review_reasons == ["judge_error"]
    assert rec.dimensions == {} and rec.summary.startswith("judge_error")


async def test_provider_errors_propagate_for_retry_routing() -> None:
    provider = ScriptedProvider([LLMRetryableError("429")])
    with pytest.raises(LLMRetryableError):
        await evaluate_call(sc.clean_call(), client_for(provider))


def test_check_failure_types_cover_every_check_type() -> None:
    assert set(CHECK_FAILURE_TYPES) == {
        "disclosure_present",
        "forbidden_absent",
        "language_match",
        "no_loop",
        "amount_confirmed",
        "tool_calls_expected",
    }
