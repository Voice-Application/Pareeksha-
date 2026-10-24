"""T-FR-SC-2: N drafts, schema-valid, in the requested mix (scripted model answers here; the live
DeepSeek run that the plan asks for is captured in proof/API-05/live_generate.py)."""

from __future__ import annotations

from typing import Any

import pytest

from pareeksha.llm.client import JSONGenerationError, LLMClient
from pareeksha.llm.config import LLMSettings
from pareeksha.scenario_gen.generator import (
    AgentBrief,
    ScenarioBatch,
    batch_problems,
    generate_scenarios,
    resolve_mix,
    split_batches,
)
from pareeksha.schemas.scenarios import ScenarioCreate
from tests.judge.scripted_llm import ScriptedScenarioLLM, scenario

BRIEF = AgentBrief(
    name="EMI Bot",
    description="Outbound EMI reminder bot",
    languages=["kn-IN", "en-IN"],
    tools=[{"name": "record_utr", "description": "Save the UTR"}],
    disclosures=[{"text": "This call is recorded"}],
    forbidden=[{"text": "legal action"}],
)


def client(provider: ScriptedScenarioLLM) -> LLMClient:
    settings = LLMSettings(deepseek_api_key="k", deepseek_caller_model="pinned-caller")
    return LLMClient(provider, settings)


async def test_ten_drafts_are_valid_scenarios_in_the_requested_mix() -> None:
    provider = ScriptedScenarioLLM()
    mix = {"happy_path": 3, "edge_case": 4, "adversarial": 3}
    out = await generate_scenarios(client(provider), BRIEF, 10, mix)
    assert len(out.scenarios) == 10 and out.calls == 1
    assert all(isinstance(s, ScenarioCreate) for s in out.scenarios)
    kinds = [next(t for t in s.tags if t in mix) for s in out.scenarios]
    assert {k: kinds.count(k) for k in mix} == mix
    assert len({s.title for s in out.scenarios}) == 10
    request = provider.requests[0]
    assert request.model == "pinned-caller" and request.temperature == 0.8  # SCENARIO_GEN
    prompt = request.messages[0].content
    assert "EMI Bot" in prompt and "record_utr" in prompt and "This call is recorded" in prompt
    assert "- 4 x edge_case" in prompt and "json" in prompt.lower()


async def test_default_mix_and_batching_for_large_requests() -> None:
    assert resolve_mix(10, {}) == {"happy_path": 3, "edge_case": 4, "adversarial": 3}
    assert sum(resolve_mix(7, {}).values()) == 7
    assert resolve_mix(1, {}) == {"edge_case": 1}
    batches = split_batches({"happy_path": 8, "edge_case": 9, "adversarial": 8})
    assert len(batches) == 3
    assert sum(sum(b.values()) for b in batches) == 25
    totals = {
        k: sum(b.get(k, 0) for b in batches) for k in ("happy_path", "edge_case", "adversarial")
    }
    assert totals == {"happy_path": 8, "edge_case": 9, "adversarial": 8}
    provider = ScriptedScenarioLLM()
    out = await generate_scenarios(client(provider), BRIEF, 25, {})
    assert len(out.scenarios) == 25 and out.calls == 3
    assert len({s.title for s in out.scenarios}) == 25


async def test_existing_titles_are_sent_and_not_reused() -> None:
    provider = ScriptedScenarioLLM()
    await generate_scenarios(client(provider), BRIEF, 3, {}, existing_titles=["Already paid"])
    assert "already paid" in provider.requests[0].messages[0].content


async def test_a_wrong_answer_is_sent_back_once_and_the_fix_is_used() -> None:
    def short_first_time(call: int, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return items[:-1] if call == 1 else items

    provider = ScriptedScenarioLLM(short_first_time)
    out = await generate_scenarios(client(provider), BRIEF, 5, {})
    assert len(out.scenarios) == 5 and len(provider.requests) == 2
    repair = provider.requests[1].messages[-1].content
    assert "expected exactly 5 scenarios, got 4" in repair


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda c, i: i[:-1], "expected exactly 5"),
        (lambda c, i: [{**x, "title": "Same"} for x in i], "titles must be unique"),
        (
            lambda c, i: [{**x, "tags": ["happy_path"]} for x in i],
            "tagged",
        ),
        (
            lambda c, i: [
                {**x, "expected_tool_calls": [{"name": "launch_missiles", "args": {}, "order": 1}]}
                for x in i
            ],
            "does not declare",
        ),
        (lambda c, i: [{**x, "surprise": 1} for x in i], "schema violations"),
        (lambda c, i: [{**x, "max_turns": 500} for x in i], "schema violations"),
    ],
)
async def test_an_answer_that_stays_wrong_after_the_repair_retry_is_an_error(
    mutate: Any, message: str
) -> None:
    provider = ScriptedScenarioLLM(mutate)
    with pytest.raises(JSONGenerationError) as err:
        await generate_scenarios(client(provider), BRIEF, 5, {})
    assert message in str(err.value) and len(provider.requests) == 2


def test_batch_problems_checks_titles_against_existing_scenarios_and_tool_less_agents() -> None:
    batch = ScenarioBatch(scenarios=[ScenarioCreate.model_validate(scenario("Taken", "edge_case"))])
    assert batch_problems(batch, {"edge_case": 1}, BRIEF, {"taken"}) is not None
    no_tools = AgentBrief(name="x")
    problem = batch_problems(
        ScenarioBatch(scenarios=[ScenarioCreate.model_validate(scenario("T", "edge_case", ["t"]))]),
        {"edge_case": 1},
        no_tools,
        set(),
    )
    assert problem is not None and "declares no tools" in problem
    ok = ScenarioBatch(scenarios=[ScenarioCreate.model_validate(scenario("Fresh", "edge_case"))])
    assert batch_problems(ok, {"edge_case": 1}, no_tools, set()) is None
