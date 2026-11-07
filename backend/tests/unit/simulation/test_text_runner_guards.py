"""Text runner: fenced simulated results and the per-reply tool-call cap."""

from __future__ import annotations

import json

import pytest

from pareeksha.agent_llm.base import ToolCallReq
from pareeksha.evaluation.checks import check_tool_calls
from pareeksha.evaluation.types import ToolCall
from pareeksha.simulation.text_runner import MAX_TOOL_CALLS_PER_REPLY, _unfence
from tests.unit.simulation.test_text_runner import (
    TOOL,
    FakeChat,
    call,
    make,
    run,
    text,
    tools_reply,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('  ```JSON\n{"a": 1}```  ', {"a": 1}),
        ('{"a": 1}', {"a": 1}),
    ],
)
def test_unfence(raw: str, expected: dict[str, int]) -> None:
    assert json.loads(_unfence(raw)) == expected


async def test_simulated_tool_accepts_fenced_json() -> None:
    spec = make()
    spec.agent.adapter_config["prompt_version"]["tools"][0]["mock"] = {"mode": "simulated"}
    # agent asks for the tool, the simulator model answers in a ```json fence, the agent replies
    chat = FakeChat(
        [tools_reply(call()), text('```json\n{"balance": 42}\n```'), text("you have 42")]
    )
    res = await run(spec, ["balance?"], chat)
    assert res.tool_calls[0].result == {"balance": 42}


async def test_tool_calls_beyond_the_cap_are_recorded_but_not_run() -> None:
    spec = make()
    forbidden = {**TOOL, "name": "waive_fee", "mock": {"mode": "static", "result": {"ok": True}}}
    spec.agent.adapter_config["prompt_version"]["tools"].append(forbidden)
    n = MAX_TOOL_CALLS_PER_REPLY + 4
    calls = [ToolCallReq(f"c{i}", "lookup", {}, "{}") for i in range(n)]
    calls[MAX_TOOL_CALLS_PER_REPLY + 1] = ToolCallReq("c-waive", "waive_fee", {}, "{}")
    chat = FakeChat([tools_reply(*calls), text("done")])
    res = await run(spec, ["x"], chat)
    assert [c.name for c in res.tool_calls] == [c.name for c in calls]  # all in the trace
    over = res.tool_calls[MAX_TOOL_CALLS_PER_REPLY:]
    assert all(c.result == {"error": "too_many_tool_calls"} for c in over)  # mocks not run
    tool_msgs = [m for m in chat.seen[1] if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == [c.id for c in calls]  # all answered
    assert all(json.loads(m.content) == {"error": "too_many_tool_calls"} for m in tool_msgs[-4:])
    assert json.loads(tool_msgs[0].content) == {"balance": 100}
    [event] = [e for e in res.events if e.type == "tool_call_limit"]
    assert event.data == {"limit": MAX_TOOL_CALLS_PER_REPLY, "requested": n}
    # the forbidden call past the cap still fails its not_called expectation
    trace = [ToolCall(name=c.name, args=c.arguments, turn_idx=c.turn_idx) for c in res.tool_calls]
    [check] = check_tool_calls([{"name": "waive_fee", "expect": "not_called"}], trace)
    assert check.check_key == "not_called:waive_fee" and check.passed is False
