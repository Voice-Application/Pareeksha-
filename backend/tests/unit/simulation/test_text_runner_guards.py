"""Text runner: fenced simulated results and the per-reply tool-call cap."""

from __future__ import annotations

import json

import pytest

from pareeksha.agent_llm.base import ToolCallReq
from pareeksha.simulation.text_runner import MAX_TOOL_CALLS_PER_REPLY, _unfence
from tests.unit.simulation.test_text_runner import FakeChat, call, make, run, text, tools_reply


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


async def test_tool_calls_beyond_the_cap_get_an_error_result() -> None:
    n = MAX_TOOL_CALLS_PER_REPLY + 4
    calls = [ToolCallReq(f"c{i}", "lookup", {}, "{}") for i in range(n)]
    chat = FakeChat([tools_reply(*calls), text("done")])
    res = await run(make(), ["x"], chat)
    assert len(res.tool_calls) == MAX_TOOL_CALLS_PER_REPLY
    tool_msgs = [m for m in chat.seen[1] if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == [f"c{i}" for i in range(n)]  # all answered
    assert all(json.loads(m.content) == {"error": "too_many_tool_calls"} for m in tool_msgs[-4:])
    assert json.loads(tool_msgs[0].content) == {"balance": 100}
    [event] = [e for e in res.events if e.type == "tool_call_limit"]
    assert event.data == {"limit": MAX_TOOL_CALLS_PER_REPLY, "requested": n}
