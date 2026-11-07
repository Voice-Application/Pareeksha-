"""``prompt_context`` appends the system prompt under test as fenced data, or leaves the
description alone."""

from __future__ import annotations

from pareeksha.agent_llm.context import PROMPT_LABEL, fence_for, prompt_context


def test_no_version_returns_description_unchanged() -> None:
    """Without a version the agent description is returned as is."""
    assert prompt_context("EMI bot", None) == "EMI bot"


def test_version_appends_system_prompt_as_fenced_data() -> None:
    """The version's system prompt follows the description as a labelled, fenced block."""
    out = prompt_context("EMI bot", {"system_prompt": "Be polite."})
    assert out == f"EMI bot\n\n{PROMPT_LABEL}\n```text\nBe polite.\n```"


def test_fence_is_longer_than_any_backtick_run_in_the_prompt() -> None:
    """The fence is longer than the longest backtick run inside the prompt."""
    assert fence_for("no fences") == "```"
    assert fence_for("```\nclose\n`````") == "``````"
