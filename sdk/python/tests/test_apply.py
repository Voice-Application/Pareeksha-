from __future__ import annotations

import pytest

from pareeksha_sdk import NotFoundError, Pareeksha
from pareeksha_sdk.apply import apply_config, resolve_suite
from pareeksha_sdk.config import ProjectConfig, ScenarioSelector, Suite
from tests.fake_platform import API_KEY, State


def cfg(**agent_extra: object) -> ProjectConfig:
    return ProjectConfig.model_validate(
        {
            "version": 1,
            "agent": {"name": "Bot", "endpoint_url": "ws://x/ws", **agent_extra},
            "scenarios": [{"title": "S1", "caller_goal": "g", "success_criteria": "s"}],
            "personas": [{"name": "P1"}],
            "noise_profiles": [{"name": "N1"}],
        }
    )


def test_agent_update_is_a_single_patch(base_url: str, state: State) -> None:
    pk = Pareeksha(base_url, API_KEY)
    assert apply_config(pk, cfg()).changed == 4
    report = apply_config(pk, cfg(glass_box=True))
    assert [(e.kind, e.action) for e in report.entries if e.action != "unchanged"] == [
        ("agent", "updated")
    ]
    assert state.agents[next(iter(state.agents))]["glass_box"] is True


def test_apply_without_libraries_only_touches_agent(base_url: str, state: State) -> None:
    pk = Pareeksha(base_url, API_KEY)
    only_agent = ProjectConfig.model_validate({"version": 1, "agent": {"name": "Bot"}})
    assert [e.kind for e in apply_config(pk, only_agent).entries] == ["agent"]
    assert state.scenarios == {}


def test_resolve_suite_by_titles_and_errors(base_url: str) -> None:
    pk = Pareeksha(base_url, API_KEY)
    with pytest.raises(NotFoundError):
        resolve_suite(pk, "Bot", Suite())
    apply_config(pk, cfg())
    resolved = resolve_suite(pk, "Bot", Suite(scenarios=ScenarioSelector(titles=["S1"])))
    assert len(resolved.scenario_ids) == 1 and len(resolved.persona_ids) == 1
    with pytest.raises(NotFoundError, match="'Nope'"):
        resolve_suite(pk, "Bot", Suite(scenarios=ScenarioSelector(titles=["Nope"])))


def test_resolve_suite_without_personas_available(base_url: str, state: State) -> None:
    pk = Pareeksha(base_url, API_KEY)
    apply_config(pk, cfg())
    state.personas.clear()
    with pytest.raises(NotFoundError, match="no persona"):
        resolve_suite(pk, "Bot", Suite())
