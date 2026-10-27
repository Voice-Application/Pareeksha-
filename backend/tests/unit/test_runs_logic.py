"""Matrix expansion and cost estimate (API-03), no I/O. Also: API-03 left no stub behind."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from pareeksha.api.main import ROUTERS
from pareeksha.llm.config import LLMSettings
from pareeksha.runs.estimate import (
    ScenarioShape,
    budget_credits,
    call_seconds,
    estimate_run,
    is_over_budget,
    remaining_budget,
)
from pareeksha.runs.matrix import expand_matrix, item_count, item_seed, unique_in_order
from pareeksha.speech.config import SpeechSettings

PACKAGE = Path(__file__).resolve().parents[2] / "pareeksha"


def ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=i + 1) for i in range(n)]


# ------------------------------------------------------------------------------------ matrix


def test_matrix_is_the_full_product_with_distinct_seeds() -> None:
    s, p, n = ids(3), ids(2), ids(2)
    cells = list(
        expand_matrix(run_seed=42, scenario_ids=s, persona_ids=p, noise_profile_ids=n, repeats=2)
    )
    assert len(cells) == item_count(3, 2, 2, 2) == 24
    keys = {(c.scenario_id, c.persona_id, c.noise_profile_id, c.seed) for c in cells}
    assert len(keys) == 24  # matches the run_items unique key
    assert {c.scenario_id for c in cells} == set(s)
    assert all(0 <= c.seed < 2**63 for c in cells)
    assert all(c.regression_test_id is None for c in cells)


def test_seeds_depend_on_the_cell_not_on_list_order() -> None:
    s, p, n = ids(2), ids(2), ids(1)
    forward = {
        (c.scenario_id, c.persona_id): c.seed
        for c in expand_matrix(
            run_seed=1, scenario_ids=s, persona_ids=p, noise_profile_ids=n, repeats=1
        )
    }
    backward = {
        (c.scenario_id, c.persona_id): c.seed
        for c in expand_matrix(
            run_seed=1,
            scenario_ids=s[::-1],
            persona_ids=p[::-1],
            noise_profile_ids=n,
            repeats=1,
        )
    }
    assert forward == backward


def test_seed_changes_with_run_seed_repeat_and_salt() -> None:
    a, b, c = ids(3)
    base = item_seed(1, a, b, c, 0)
    assert item_seed(1, a, b, c, 0) == base
    assert len({base, item_seed(2, a, b, c, 0), item_seed(1, a, b, c, 1)}) == 3
    assert item_seed(1, a, b, c, 0, salt="t1") != item_seed(1, a, b, c, 0, salt="t2")


def test_repeated_ids_collapse_keeping_first_position() -> None:
    a, b = ids(2)
    assert unique_in_order([b, a, b, a]) == [b, a]
    cells = list(
        expand_matrix(
            run_seed=0, scenario_ids=[a, a], persona_ids=[b], noise_profile_ids=[a], repeats=1
        )
    )
    assert len(cells) == 1


# ------------------------------------------------------------------------------------ estimate


def speech(**rates: float) -> SpeechSettings:
    return SpeechSettings(_env_file=None, **rates)  # type: ignore[arg-type]


def llm(**rates: float) -> LLMSettings:
    return LLMSettings(_env_file=None, **rates)  # type: ignore[arg-type]


def test_call_length_is_turns_capped_by_the_agents_limit() -> None:
    assert call_seconds(10, 300) == 60
    assert call_seconds(60, 120) == 120


def test_estimate_counts_audio_and_llm_calls() -> None:
    result = estimate_run(
        [ScenarioShape(max_turns=10), ScenarioShape(max_turns=20)],
        cells_per_scenario=4,
        max_call_seconds=300,
        speech=speech(),
        llm=llm(),
    )
    assert result.stt_seconds == (60 + 120) * 4
    assert result.tts_seconds == (60 + 120) * 4 / 2
    assert result.judge_calls == 8
    assert result.caller_llm_calls == (5 + 10) * 4
    assert result.est_cost == 0  # no COST_* rates configured: nothing to charge


def test_estimate_prices_stt_tts_and_llm_with_the_configured_rates() -> None:
    result = estimate_run(
        [ScenarioShape(max_turns=10)],
        cells_per_scenario=1,
        max_call_seconds=300,
        speech=speech(cost_stt_stream_per_min=6, cost_tts_per_1k_chars=2),
        llm=llm(cost_deepseek_per_1k_input_tokens=1, cost_deepseek_per_1k_output_tokens=2),
    )
    stt = 60 / 60 * 6  # 60 s of audio
    tts = 30 * 15 / 1000 * 2  # 30 s spoken at 15 characters a second
    tokens_in = 5 * 800 + 4000
    tokens_out = 5 * 80 + 800
    expected = stt + tts + tokens_in / 1000 * 1 + tokens_out / 1000 * 2
    assert result.est_cost == pytest.approx(expected, abs=0.01)


def test_text_only_dry_run_skips_speech() -> None:
    result = estimate_run(
        [ScenarioShape(max_turns=10)],
        cells_per_scenario=2,
        max_call_seconds=300,
        text_only=True,
        speech=speech(cost_stt_stream_per_min=6, cost_tts_per_1k_chars=2),
        llm=llm(),
    )
    assert result.stt_seconds == result.tts_seconds == 0 and result.est_cost == 0
    assert result.judge_calls == 2 and result.caller_llm_calls == 10


def test_budget_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BUDGET_CREDITS", raising=False)
    assert budget_credits() is None and remaining_budget(10) is None
    monkeypatch.setenv("BUDGET_CREDITS", "  ")
    assert budget_credits() is None
    monkeypatch.setenv("BUDGET_CREDITS", "not a number")
    assert budget_credits() is None
    monkeypatch.setenv("BUDGET_CREDITS", "5000")
    assert budget_credits() == 5000 and remaining_budget(1234.567) == 3765.43
    assert remaining_budget(10, budget=100) == 90
    assert is_over_budget(10.01, 10.0) and not is_over_budget(10.0, 10.0)
    assert not is_over_budget(1e9, None)  # no budget configured: no guard


# ------------------------------------------------------------------------------------ stubs


def test_no_stub_api03_marker_remains_in_the_source() -> None:
    offenders = [
        str(path.relative_to(PACKAGE))
        for path in PACKAGE.rglob("*.py")
        if "STUB(API-03)" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_run_routes_are_declared() -> None:
    routes = {
        (method, route.path)  # type: ignore[attr-defined]
        for router in ROUTERS
        for route in router.routes
        for method in route.methods  # type: ignore[attr-defined]
    }
    assert {
        ("POST", "/runs"),
        ("POST", "/runs:estimate"),
        ("GET", "/runs"),
        ("GET", "/runs/{run_id}"),
        ("GET", "/runs/{run_id}/items"),
        ("POST", "/runs/{run_id}/cancel"),
    } <= routes
