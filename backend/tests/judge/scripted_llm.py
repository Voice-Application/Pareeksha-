"""A scripted LLM provider that answers the scenario-generation prompt like a model would."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from pareeksha.llm.base import (
    JSONCompletionRequest,
    JSONCompletionResult,
    LLMProvider,
    LLMProviderName,
    LLMUsage,
)

Mutator = Callable[[int, list[dict[str, Any]]], list[dict[str, Any]]]


def scenario(title: str, kind: str, tools: list[str] | None = None) -> dict[str, Any]:
    return {
        "title": title,
        "caller_goal": f"Goal for {title}",
        "fixtures": {"customer_name": "Test Person", "loan_id": "SHK-000001"},
        "reveal_rules": "Reveal only when asked.",
        "success_criteria": f"Criteria for {title}",
        "must_say": ["confirm the amount"],
        "must_not_say": ["threaten"],
        "expected_tool_calls": [{"name": t, "args": {}, "order": 1} for t in tools or []],
        "caller_speaks_first": False,
        "max_turns": 12,
        "tags": [kind, "topic"],
    }


class ScriptedScenarioLLM(LLMProvider):
    """Reads "Write N scenarios" and "- n x kind" from the prompt and answers accordingly.

    ``mutate(call_number, scenarios)`` lets a test break the answer (wrong count, duplicate
    titles, invented tools) on chosen calls; the repair retry is the next call number.
    """

    name = LLMProviderName.DEEPSEEK

    def __init__(self, mutate: Mutator | None = None, fail_with: Exception | None = None) -> None:
        self.requests: list[JSONCompletionRequest] = []
        self.mutate = mutate
        self.fail_with = fail_with

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        self.requests.append(request)
        if self.fail_with is not None:
            raise self.fail_with
        prompt = request.messages[0].content
        mix = [(int(n), kind) for n, kind in re.findall(r"^- (\d+) x (\w+)$", prompt, re.M)]
        items = [
            scenario(f"{kind} case {len(self.requests)}-{i}", kind, ["record_utr"])
            for n, kind in mix
            for i in range(n)
        ]
        if self.mutate is not None:
            items = self.mutate(len(self.requests), items)
        return JSONCompletionResult(
            provider=self.name,
            model=request.model,
            text=json.dumps({"scenarios": items}),
            usage=LLMUsage(input_tokens=1200, output_tokens=300 * len(items)),
            latency_ms=5,
        )

    async def aclose(self) -> None:
        return None
