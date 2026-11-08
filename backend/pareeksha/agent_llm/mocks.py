"""Resolve a tool call to its mocked result."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from pareeksha.evaluation.checks import _value_eq
from pareeksha.schemas.prompts import PromptTool

Simulate = Callable[[PromptTool, dict[str, Any]], Awaitable[dict[str, Any]]]


async def mock_result(
    tool: PromptTool,
    arguments: dict[str, Any],
    override: dict[str, Any] | None,
    simulate: Simulate | None = None,
) -> dict[str, Any]:
    """Order: ``override`` -> mode (``by_args`` first matching case else ``result``; ``static``;
    ``simulated`` via ``simulate``, any failure -> ``mock_unavailable``)."""
    if "_raw" in arguments:
        return {"error": "invalid_arguments"}
    if override is not None:
        return override
    spec = tool.mock
    if spec.mode == "by_args":
        for case in spec.cases:
            if all(k in arguments and _value_eq(v, arguments[k]) for k, v in case.when.items()):
                return case.result
        return spec.result
    if spec.mode == "simulated":
        try:
            if simulate is None:
                raise RuntimeError("no simulator")
            return await simulate(tool, arguments)
        except Exception:
            return {"error": "mock_unavailable"}
    return spec.result
