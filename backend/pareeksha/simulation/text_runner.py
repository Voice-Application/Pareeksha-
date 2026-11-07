"""Text runner: a prompt agent's scenario as a typed conversation, producing the voice path's
``CallResult`` (so storage, evaluation, judge, compare and sinks run unchanged).

The caller brain talks to the customer's model through ``agent_llm``; tool calls are answered by
mocks (``agent_llm.mocks.mock_result``).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from pareeksha.agent_llm.base import AgentLLMError, AgentMessage, ChatProvider, ChatReply, ToolSpec
from pareeksha.agent_llm.mocks import mock_result
from pareeksha.llm.caller import HistoryLine
from pareeksha.rag.retriever import Retriever, build_retriever
from pareeksha.schemas.calls import EndReason
from pareeksha.schemas.prompts import PromptTool, PromptVersionOut
from pareeksha.simulation.models import (
    CallEvent,
    CallResult,
    CallSpec,
    RetrievalRecord,
    ToolCallRecord,
    TurnRecord,
)
from pareeksha.simulation.runtime import CallerSource

_SIMULATE_SYSTEM = (
    "You simulate the backend of a tool for testing. Reply with only one JSON object: "
    "the tool's result for the given arguments."
)

#: Tool calls processed per model reply; the rest get an error result.
MAX_TOOL_CALLS_PER_REPLY = 16

_FENCE = re.compile(r"^```[A-Za-z0-9_-]*\s*\n(.*?)\n?```$", re.DOTALL)


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
    retriever: Retriever | None = None,
) -> CallResult:
    version = PromptVersionOut.model_validate(spec.agent.adapter_config["prompt_version"])
    scenario = spec.scenario
    t0 = clock()
    turns: list[TurnRecord] = []
    tool_calls: list[ToolCallRecord] = []
    events: list[CallEvent] = []
    usage: list[Any] = []
    retrievals: list[RetrievalRecord] = []
    rag: dict[str, Any] | None = spec.agent.adapter_config.get("rag")
    if rag is not None and rag["config"]["mode"] == "off":
        rag = None  # a baseline run: the store only carries the KB's local-only flag
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
            retrievals=retrievals,
            error=error,
            glass_box=True,
        )

    async def ask(
        msgs: list[AgentMessage], tools: list[ToolSpec], purpose: str | None = None
    ) -> ChatReply:
        reply = await chat.chat(msgs, tools, model=version.model, temperature=version.temperature)
        log(
            "agent_llm_usage",
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            latency_ms=reply.latency_ms,
            model=version.model,
            # "tool_simulation" is test scaffolding, not production cost
            **({"purpose": purpose} if purpose else {}),
        )
        return reply

    async def simulate(tool: PromptTool, arguments: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            f"Tool: {tool.name}\nDescription: {tool.description}\n"
            f"Arguments: {json.dumps(arguments)}\nReturn the result as a JSON object."
        )
        reply = await ask(
            [AgentMessage("system", _SIMULATE_SYSTEM), AgentMessage("user", prompt)],
            [],
            purpose="tool_simulation",
        )
        result = json.loads(_unfence(reply.text))
        if not isinstance(result, dict):
            raise ValueError("simulated result is not an object")
        return result

    def override_for(name: str) -> dict[str, Any] | None:
        for exp in scenario.expected_tool_calls:
            if exp.get("name") == name and isinstance(exp.get("mock_result"), dict):
                return dict(exp["mock_result"])
        return None

    async def add_context(query: str, turn_idx: int) -> None:
        """Retrieve for this turn and put the context into the system prompt (never fatal)."""
        nonlocal retriever
        assert rag is not None
        cfg = rag["config"]
        context = ""
        outcome_fields: dict[str, Any] = {}
        t = clock()
        retriever_total_ms: int | None = None
        try:
            if cfg["mode"] == "full_context":
                context = rag["full_context_text"]
                outcome_fields = {"queries": [query], "results": []}
            else:
                if retriever is None:
                    retriever = build_retriever(
                        rag,
                        spec.agent.adapter_secrets,
                        model=version.model,
                        temperature=version.temperature,
                    )
                out = await retriever.retrieve(query, chat=chat)
                for w in out.warnings:
                    log(w)
                context = out.context
                retriever_total_ms = out.timings.get("total_ms")
                outcome_fields = {
                    "queries": out.queries,
                    "results": out.results,
                    "timings": out.timings,
                    "usage": out.usage,
                }
        except Exception as exc:
            log("retrieval_failed", error=str(exc)[:200], turn_idx=turn_idx)
        # the retriever's own total leaves out the (cold-start) model load; wall clock includes it
        total_ms = (
            retriever_total_ms if retriever_total_ms is not None else int((clock() - t) * 1000)
        )
        prompt = version.system_prompt
        if "{{context}}" in prompt:
            prompt = prompt.replace("{{context}}", context)  # every occurrence, same context
        elif context:
            prompt = f"{prompt}\n\nRetrieved context:\n{context}"
        messages[0] = AgentMessage("system", prompt)
        if not outcome_fields:
            return
        n = len(outcome_fields.get("results", []))
        timings = {**outcome_fields.get("timings", {}), "total_ms": total_ms}
        log("retrieval", total_ms=total_ms, n_results=n)
        retrievals.append(
            RetrievalRecord(
                turn_idx=turn_idx,
                rag_config=cfg,
                index_id=rag.get("index_id"),
                query=query,
                queries=outcome_fields["queries"],
                results=outcome_fields["results"],
                context_chars=len(context),
                timings=timings,
                usage=outcome_fields.get("usage", {}),
            )
        )

    def timed_out() -> bool:
        return clock() - t0 > spec.max_call_seconds

    if not scenario.caller_speaks_first:
        log("caller_first_text_mode")
    log("call_start", language=spec.language, text_mode=True)

    for n in range(1, scenario.max_turns + 1):
        if timed_out():
            return finish("timeout")
        line = await caller.next_line(spec.persona, scenario, list(history), n)
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
        if rag is not None:
            await add_context(line.utterance, agent_idx)
        for _ in range(version.max_tool_rounds):
            if timed_out():
                return finish("timeout")
            try:
                reply = await ask(messages, specs)
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
                if (
                    i >= MAX_TOOL_CALLS_PER_REPLY
                ):  # still answer it: providers need one result per call
                    messages.append(
                        AgentMessage(
                            "tool",
                            json.dumps({"error": "too_many_tool_calls"}),
                            tool_call_id=tc.id,
                            name=tc.name,
                        )
                    )
                    continue
                tool = tools_by_name.get(tc.name)
                if tool is None:
                    result: dict[str, Any] = {"error": "unknown_tool"}
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
