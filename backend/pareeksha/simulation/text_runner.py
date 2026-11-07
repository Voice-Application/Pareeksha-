"""Text runner: a prompt agent's scenario as a typed conversation, producing the voice path's
``CallResult`` (so storage, evaluation, judge, compare and sinks run unchanged).

The caller brain talks to the customer's model through ``agent_llm``; tool calls are answered by
mocks (``agent_llm.mocks.mock_result``).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from pareeksha.agent_llm.base import AgentLLMError, AgentMessage, ChatProvider, ChatReply, ToolSpec
from pareeksha.agent_llm.mocks import mock_result
from pareeksha.llm.caller import HistoryLine
from pareeksha.schemas.calls import EndReason
from pareeksha.schemas.prompts import PromptTool, PromptVersionOut
from pareeksha.simulation.models import CallEvent, CallResult, CallSpec, ToolCallRecord, TurnRecord
from pareeksha.simulation.runtime import CallerSource

_SIMULATE_SYSTEM = (
    "You simulate the backend of a tool for testing. Reply with only one JSON object: "
    "the tool's result for the given arguments."
)

#: Tool calls executed per model reply; the rest are recorded with an error result, not run.
MAX_TOOL_CALLS_PER_REPLY = 16

_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*?)\n?```$", re.DOTALL)

T = TypeVar("T")


class _CallTimeout(Exception):
    """The call's ``max_call_seconds`` ran out while waiting for the caller or the agent."""


def _unfence(text: str) -> str:
    """The body of a single surrounding ```json fence (models often wrap JSON in one)."""
    m = _FENCE.match(text.strip())
    return m.group(1) if m else text


async def run_text_call(
    spec: CallSpec,
    *,
    caller: CallerSource,
    chat: ChatProvider,
    clock: Callable[[], float] = time.monotonic,
) -> CallResult:
    """Run the scenario as a typed conversation between the caller and the version's model.

    Tool calls are answered by mocks, at most ``MAX_TOOL_CALLS_PER_REPLY`` per reply. The call ends
    when the caller hangs up, at ``max_turns`` or the time limit, when the agent goes silent (or
    only calls tools for ``max_tool_rounds``), or on a provider error.
    """
    version = PromptVersionOut.model_validate(spec.agent.adapter_config["prompt_version"])
    scenario = spec.scenario
    t0 = clock()
    turns: list[TurnRecord] = []
    tool_calls: list[ToolCallRecord] = []
    events: list[CallEvent] = []
    usage: list[Any] = []
    history: list[HistoryLine] = []
    messages = [AgentMessage("system", version.system_prompt)]
    specs = [ToolSpec(t.name, t.description, t.parameters) for t in version.tools]
    tools_by_name = {t.name: t for t in version.tools}

    def now() -> int:
        return int((clock() - t0) * 1000)

    def log(type_: str, **data: Any) -> None:
        events.append(CallEvent(t_ms=now(), type=type_, data=data))

    def finish(reason: EndReason, error: str | None = None) -> CallResult:
        log("call_end", reason=reason, error=error)
        return CallResult(
            call_id=spec.call_id,
            end_reason=reason,
            duration_ms=now(),
            turns=turns,
            tool_calls=tool_calls,
            events=events,
            usage=usage,
            error=error,
            glass_box=True,
        )

    async def before_deadline(aw: Awaitable[T]) -> T:
        """``aw``, abandoned with :class:`_CallTimeout` once ``max_call_seconds`` run out."""
        deadline = asyncio.timeout(max(spec.max_call_seconds - (clock() - t0), 0))
        try:
            async with deadline:
                return await aw
        except TimeoutError:
            if deadline.expired():
                raise _CallTimeout from None
            raise

    async def ask(msgs: list[AgentMessage], tools: list[ToolSpec]) -> ChatReply:
        reply = await before_deadline(
            chat.chat(msgs, tools, model=version.model, temperature=version.temperature)
        )
        log(
            "agent_llm_usage",
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            latency_ms=reply.latency_ms,
            model=version.model,
        )
        return reply

    async def simulate(tool: PromptTool, arguments: dict[str, Any]) -> dict[str, Any]:
        """Ask the model to invent the tool's result for ``arguments``; it must be a JSON object."""
        prompt = (
            f"Tool: {tool.name}\nDescription: {tool.description}\n"
            f"Arguments: {json.dumps(arguments)}\nReturn the result as a JSON object."
        )
        reply = await ask(
            [AgentMessage("system", _SIMULATE_SYSTEM), AgentMessage("user", prompt)], []
        )
        result = json.loads(_unfence(reply.text))
        if not isinstance(result, dict):
            raise ValueError("simulated result is not an object")
        return result

    def override_for(name: str) -> dict[str, Any] | None:
        """The scenario's ``mock_result`` for tool ``name``, if an expected call defines one."""
        for exp in scenario.expected_tool_calls:
            if exp.get("name") == name and isinstance(exp.get("mock_result"), dict):
                return dict(exp["mock_result"])
        return None

    def timed_out() -> bool:
        return clock() - t0 > spec.max_call_seconds

    if not scenario.caller_speaks_first:
        log("caller_first_text_mode")
    log("call_start", language=spec.language, text_mode=True)

    for n in range(1, scenario.max_turns + 1):
        if timed_out():
            return finish("timeout")
        try:
            line = await before_deadline(caller.next_line(spec.persona, scenario, list(history), n))
        except _CallTimeout:
            return finish("timeout")
        if line.usage is not None:
            usage.append(line.usage)
        at = now()
        turns.append(
            TurnRecord(
                idx=len(turns),
                speaker="caller",
                text=line.utterance,
                start_ms=at,
                end_ms=at,
                ground_truth_text=line.utterance,
                kind="reply",
            )
        )
        history.append(HistoryLine("caller", line.utterance))
        messages.append(AgentMessage("user", line.utterance))
        if line.end_call:
            # same rule as the voice director: gave up only when the persona's patience ran out
            gave_up = n >= spec.persona.patience_turns
            return finish("gave_up" if gave_up else "goal_achieved")

        agent_idx = len(turns)
        started = now()
        for _ in range(version.max_tool_rounds):
            if timed_out():
                return finish("timeout")
            try:
                reply = await ask(messages, specs)
            except _CallTimeout:
                return finish("timeout")
            except AgentLLMError as exc:
                has_agent_turn = any(t.speaker == "agent" for t in turns)
                return finish("infra_error" if has_agent_turn else "connect_failed", str(exc))
            if not reply.tool_calls:
                if not reply.text.strip():
                    log("empty_reply")
                    return finish("agent_silent")
                turns.append(
                    TurnRecord(
                        idx=agent_idx,
                        speaker="agent",
                        text=reply.text,
                        start_ms=started,
                        end_ms=now(),
                        glass_box_text=reply.text,
                    )
                )
                history.append(HistoryLine("agent", reply.text))
                messages.append(AgentMessage("assistant", reply.text))
                break
            # pass the provider's own ToolCallReq objects back unchanged
            messages.append(AgentMessage("assistant", reply.text, reply.tool_calls))
            if len(reply.tool_calls) > MAX_TOOL_CALLS_PER_REPLY:
                log(
                    "tool_call_limit",
                    limit=MAX_TOOL_CALLS_PER_REPLY,
                    requested=len(reply.tool_calls),
                )
            for i, tc in enumerate(reply.tool_calls):
                tool = tools_by_name.get(tc.name)
                if i >= MAX_TOOL_CALLS_PER_REPLY:
                    # recorded (so not_called sees it) and answered, but its mock is not run
                    result: dict[str, Any] = {"error": "too_many_tool_calls"}
                elif tool is None:
                    result = {"error": "unknown_tool"}
                else:
                    result = await mock_result(
                        tool, tc.arguments, override_for(tc.name), simulate=simulate
                    )
                tool_calls.append(
                    ToolCallRecord(
                        seq=len(tool_calls),
                        name=tc.name,
                        arguments=tc.arguments,
                        result=result,
                        at_ms=now(),
                        turn_idx=agent_idx,
                    )
                )
                messages.append(
                    AgentMessage("tool", json.dumps(result), tool_call_id=tc.id, name=tc.name)
                )
        else:
            log("tool_round_limit", max_tool_rounds=version.max_tool_rounds)
            return finish("agent_silent")

    return finish("max_turns")
