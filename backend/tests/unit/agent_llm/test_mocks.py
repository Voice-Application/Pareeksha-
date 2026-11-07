from typing import Any

from pareeksha.agent_llm.mocks import mock_result
from pareeksha.schemas.prompts import MockCase, MockSpec, PromptTool


def _tool(mock: MockSpec) -> PromptTool:
    return PromptTool(name="t", parameters={"type": "object"}, mock=mock)


BY_ARGS = MockSpec(
    mode="by_args",
    result={"r": "default"},
    cases=[
        MockCase(when={"id": 1}, result={"r": "one"}),
        MockCase(when={"id": 1, "x": "y"}, result={"r": "later"}),
    ],
)


async def test_override_wins() -> None:
    """A scenario's override beats the tool's static mock result."""
    tool = _tool(MockSpec(result={"r": "static"}))
    assert await mock_result(tool, {}, {"r": "ov"}) == {"r": "ov"}


async def test_static() -> None:
    """A static mock returns its fixed result."""
    assert await mock_result(_tool(MockSpec(result={"r": "s"})), {}, None) == {"r": "s"}


async def test_by_args_first_matching_case() -> None:
    """A ``by_args`` mock answers with the first matching case, not a later more specific one."""
    assert await mock_result(_tool(BY_ARGS), {"id": "1", "x": "y"}, None) == {"r": "one"}


async def test_by_args_falls_back_to_result() -> None:
    """A ``by_args`` mock without a matching case returns its default result."""
    assert await mock_result(_tool(BY_ARGS), {"id": 2}, None) == {"r": "default"}


async def test_simulated_failure_returns_error() -> None:
    """A failing or missing simulator gives ``mock_unavailable``."""

    async def boom(tool: PromptTool, args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("x")

    tool = _tool(MockSpec(mode="simulated"))
    assert await mock_result(tool, {}, None, boom) == {"error": "mock_unavailable"}
    assert await mock_result(tool, {}, None) == {"error": "mock_unavailable"}


async def test_simulated_ok() -> None:
    """A simulated mock returns what the simulator produced."""

    async def ok(tool: PromptTool, args: dict[str, Any]) -> dict[str, Any]:
        return {"echo": args}

    assert await mock_result(_tool(MockSpec(mode="simulated")), {"a": 1}, None, ok) == {
        "echo": {"a": 1}
    }


async def test_raw_arguments_return_invalid_arguments() -> None:
    """Unparseable arguments get ``invalid_arguments``, even when an override exists."""
    assert await mock_result(_tool(MockSpec()), {"_raw": "{bad"}, {"r": 1}) == {
        "error": "invalid_arguments"
    }
