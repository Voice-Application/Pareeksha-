"""``prompt_context`` appends the system prompt under test, or leaves the description alone."""

from __future__ import annotations

from pareeksha.agent_llm.context import prompt_context


def test_no_version_returns_description_unchanged() -> None:
    assert prompt_context("EMI bot", None) == "EMI bot"


def test_version_appends_system_prompt() -> None:
    out = prompt_context("EMI bot", {"system_prompt": "Be polite."})
    assert out == "EMI bot\n\nSystem prompt under test:\nBe polite."
