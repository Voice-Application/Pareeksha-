"""Quick-test helpers: cutting pasted text, safe pages, the customer record in the prompt."""

from __future__ import annotations

import pytest

from pareeksha.llm.config import LLMSettings
from pareeksha.quicktest.assistant import cut, safe_path
from pareeksha.quicktest.service import agent_model, agent_prompt
from pareeksha.schemas.quick_tests import AssistantMessage, QuickTestPlan, TextSource

PASTED = "test this please:\nYou are a bank bot.\nNever share balances.\nthanks"


def msgs(*texts: str) -> list[AssistantMessage]:
    """User messages with the given texts."""
    return [AssistantMessage(role="user", content=t) for t in texts]


def test_cut_takes_the_exact_text_between_the_markers() -> None:
    """The cut runs from the start marker to the end marker."""
    src = TextSource(message=0, start="You are a bank", end="share balances.")
    assert cut(msgs(PASTED), src) == "You are a bank bot.\nNever share balances."


def test_cut_matches_markers_ignoring_case_and_widens_when_missing() -> None:
    """Markers match without case; a missing one widens the cut."""
    assert cut(msgs(PASTED), TextSource(message=0, start="you are a BANK")) == (
        "You are a bank bot.\nNever share balances.\nthanks"
    )
    assert cut(msgs(PASTED), TextSource(message=0, start="not there", end="nope")) == PASTED.strip()


def test_cut_refuses_assistant_turns_and_unknown_messages() -> None:
    """Only user messages that exist can be cut."""
    history = [AssistantMessage(role="assistant", content="hello"), *msgs(PASTED)]
    assert cut(history, TextSource(message=0)) is None
    assert cut(history, TextSource(message=5)) is None
    assert cut(history, None) is None


@pytest.mark.parametrize(
    ("path", "ok"),
    [
        ("/test", True),
        ("/test/123", True),
        ("/settings/llm", True),
        ("/", True),
        ("//evil.example", False),
        ("https://evil.example", False),
        ("/../etc", False),
        ("/testing", False),
    ],
)
def test_safe_path(path: str, ok: bool) -> None:
    """Only in-app pages are opened."""
    assert (safe_path(path) is not None) is ok


def test_agent_prompt_uses_the_placeholder_or_appends_the_record() -> None:
    """The record replaces the placeholder or is appended."""
    assert agent_prompt("Hi {{user_details}} bye", "Name: A") == "Hi Name: A bye"
    assert agent_prompt("Hi", "Name: A") == "Hi\n\n## Customer record\nName: A"
    assert agent_prompt("Hi", "  ") == "Hi"


def test_agent_model_follows_the_platform_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """The bot runs on the platform's provider and fast model."""
    s = LLMSettings(_env_file=None, deepseek_api_key="k")  # type: ignore[call-arg]
    assert agent_model(s) == ("deepseek", "deepseek-flash", None, "k")
    custom = s.model_copy(
        update={"deepseek_guard_base_url": True, "deepseek_base_url": "https://llm.example/v1"}
    )
    assert agent_model(custom)[0:3] == (
        "openai_compatible",
        "deepseek-flash",
        "https://llm.example/v1",
    )


def test_plan_rejects_scenarios_citing_unknown_rules() -> None:
    """A scenario may only cite rules of the plan."""
    base = {
        "agent_name": "Bot",
        "rules": [{"id": "a", "kind": "forbidden", "text": "x"}],
        "scenarios": [
            {"title": "t", "caller_goal": "g", "success_criteria": "c", "rule_ids": ["b"]}
        ],
    }
    with pytest.raises(ValueError, match="unknown rules"):
        QuickTestPlan.model_validate(base)
