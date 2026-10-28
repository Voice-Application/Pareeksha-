"""FR-RG-2 verdict, the finalizer's use of it, and the run cost estimate."""

from __future__ import annotations

import uuid

import pytest

from pareeksha.evaluation.handlers import RunItemOutcome, RunState, item_passes_suite, summarize_run
from pareeksha.llm.config import LLMSettings
from pareeksha.regression.estimate import estimate_run
from pareeksha.regression.verdict import DEFAULT_TOLERANCE, regression_passed
from pareeksha.speech.config import SpeechSettings


@pytest.mark.parametrize(
    ("score", "critical", "baseline", "tolerance", "expected"),
    [
        (80, False, 80, 5, True),
        (75, False, 80, 5, True),  # exactly baseline - tolerance passes
        (74.99, False, 80, 5, False),
        (100, True, 80, 5, False),  # a critical failure fails whatever the score
        (None, False, 80, 5, False),
        (60, False, 60, 0, True),
        (59.9, False, 60, 0, False),
    ],
)
def test_regression_passed(
    score: float | None, critical: bool, baseline: float, tolerance: float, expected: bool
) -> None:
    assert regression_passed(score, critical, baseline, tolerance) is expected


def test_default_tolerance_is_five() -> None:
    assert DEFAULT_TOLERANCE == 5.0


def item(score: float | None, **kw: object) -> RunItemOutcome:
    return RunItemOutcome(
        status=str(kw.pop("status", "evaluated")),
        overall_score=score,
        passed=None if score is None else score >= 80,
        **kw,  # type: ignore[arg-type]
    )


def state(*items: RunItemOutcome, kind: str = "regression") -> RunState:
    return RunState(uuid.uuid4(), uuid.uuid4(), kind, "running", items)  # type: ignore[arg-type]


def test_suite_uses_baseline_minus_tolerance_not_the_judge_pass_mark() -> None:
    # 72 is a judge fail (< 80) but meets baseline 70 - tolerance 5
    ok = state(item(72, baseline_score=70, tolerance=5))
    assert summarize_run(ok).suite_passed is True
    # 88 is a judge pass but misses baseline 95 - tolerance 5
    bad = state(item(88, baseline_score=95, tolerance=5))
    assert summarize_run(bad).suite_passed is False


def test_suite_fails_if_any_blocking_test_fails() -> None:
    items = [
        item(90, baseline_score=80, tolerance=5),
        item(70, baseline_score=80, tolerance=5),  # 70 < 75
        item(95, baseline_score=80, tolerance=5),
    ]
    assert summarize_run(state(*items)).suite_passed is False
    assert summarize_run(state(items[0], items[2])).suite_passed is True


def test_critical_failure_fails_the_suite_at_any_score() -> None:
    assert (
        summarize_run(state(item(99, critical_failure=True, baseline_score=50))).suite_passed
        is False
    )


def test_non_blocking_failures_do_not_fail_the_suite() -> None:
    items = [item(90, baseline_score=80), item(10, baseline_score=80, blocking=False)]
    assert summarize_run(state(*items)).suite_passed is True


def test_an_unevaluated_blocking_item_fails_the_suite() -> None:
    for status in ("error", "judge_error", "cancelled", "skipped_budget"):
        assert item_passes_suite(item(None, status=status, baseline_score=10)) is False


def test_no_thresholds_falls_back_to_judge_verdict_and_matrix_runs_have_no_suite() -> None:
    assert item_passes_suite(item(85)) is True
    assert item_passes_suite(item(70)) is False
    assert summarize_run(state(item(70), kind="matrix")).suite_passed is None


def test_estimate_scales_with_turns_and_prices_from_settings() -> None:
    speech = SpeechSettings(cost_tts_per_1k_chars=2.0, cost_stt_stream_per_min=3.0)
    llm = LLMSettings(
        deepseek_api_key="k",
        cost_deepseek_per_1k_input_tokens=1.0,
        cost_deepseek_per_1k_output_tokens=2.0,
    )
    one = estimate_run([10], speech=speech, llm=llm)
    assert (one.judge_calls, one.caller_llm_calls) == (1, 5)
    assert one.tts_seconds == 20.0 and one.stt_seconds == 30.0
    # tts 20 s * 14 chars/s = 280 chars -> 0.56; stt 0.5 min -> 1.5;
    # caller 5*(800,60) tokens -> 4+0.6;
    # judge (6000,1200) -> 6 + 2.4
    assert one.est_cost == pytest.approx(0.56 + 1.5 + 4.6 + 8.4, abs=0.01)
    three = estimate_run([10, 10, 10], speech=speech, llm=llm)
    assert three.est_cost == pytest.approx(3 * one.est_cost, abs=0.02)


def test_estimate_without_rates_costs_nothing_but_still_counts_work() -> None:
    est = estimate_run([8, 12], speech=SpeechSettings(), llm=LLMSettings(deepseek_api_key="k"))
    assert est.est_cost == 0.0 and est.judge_calls == 2 and est.caller_llm_calls == 10
