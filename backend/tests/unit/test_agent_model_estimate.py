"""The model under test in the pre-run estimate (prompt agents): token math and pricing."""

from __future__ import annotations

import pytest

from pareeksha.runs.estimate import (
    AGENT_TOKENS_OUT,
    AgentModelLoad,
    ScenarioShape,
    agent_model_tokens,
    estimate_run,
)

NO_PRICES = {"text_only": True}  # no TTS/STT; caller and judge rates are unset in tests


@pytest.fixture(autouse=True)
def _no_cost_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "COST_DEEPSEEK_PER_1K_INPUT_TOKENS",
        "COST_DEEPSEEK_PER_1K_OUTPUT_TOKENS",
        "COST_GEMINI_PER_1K_INPUT_TOKENS",
        "COST_GEMINI_PER_1K_OUTPUT_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_tokens_per_call_grow_with_context_turns_and_tools() -> None:
    plain = AgentModelLoad(prompt_chars=400)
    rounds, tin, tout = agent_model_tokens(4, plain)
    # 4 replies; each resends 100 prompt tokens plus half the call's history (4 x 120 / 2)
    assert (rounds, tin, tout) == (4.0, 4 * (100 + 240), 4 * AGENT_TOKENS_OUT)
    with_rag = agent_model_tokens(4, AgentModelLoad(prompt_chars=400, context_chars=2400))[1]
    assert with_rag == tin + 4 * 600  # 2,400 context characters = 600 tokens per reply
    tools = agent_model_tokens(4, AgentModelLoad(prompt_chars=400, has_tools=True))
    assert tools[0] == 6.0 and tools[2] == 6 * AGENT_TOKENS_OUT  # 1.5 rounds per reply


def test_priced_model_adds_its_cost() -> None:
    load = AgentModelLoad(prompt_chars=400, input_per_m=13.0, output_per_m=53.0)
    est = estimate_run(
        [ScenarioShape(max_turns=4)], cells_per_scenario=10, max_call_seconds=300, agent=load,
        **NO_PRICES,  # type: ignore[arg-type]
    )  # fmt: skip
    tin, tout = 10 * 4 * (100 + 240), 10 * 4 * AGENT_TOKENS_OUT
    assert est.agent_llm_calls == 40 and est.agent_llm_tokens == tin + tout
    assert est.est_cost == round(tin * 13 / 1e6 + tout * 53 / 1e6, 2)
    assert est.agent_llm_unpriced is False


def test_unpriced_model_counts_tokens_but_no_cost() -> None:
    est = estimate_run(
        [ScenarioShape(max_turns=4)], cells_per_scenario=10, max_call_seconds=300,
        agent=AgentModelLoad(prompt_chars=400, input_per_m=13.0),  # no output price
        **NO_PRICES,  # type: ignore[arg-type]
    )  # fmt: skip
    assert est.agent_llm_tokens > 0 and est.est_cost == 0
    assert est.agent_llm_unpriced is True


def test_other_adapters_have_no_agent_model() -> None:
    est = estimate_run(
        [ScenarioShape(max_turns=4)], cells_per_scenario=1, max_call_seconds=300, **NO_PRICES,  # type: ignore[arg-type]
    )  # fmt: skip
    assert (est.agent_llm_calls, est.agent_llm_tokens, est.agent_llm_unpriced) == (0, 0, False)
