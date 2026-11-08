"""Text runner: scripted caller + scripted fake chat provider, no network, no DB."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from pareeksha.adapters.base import AgentTarget
from pareeksha.agent_llm.base import AgentLLMError, AgentMessage, ChatReply, ToolCallReq, ToolSpec
from pareeksha.audio.profiles import get_profile
from pareeksha.schemas.prompts import PromptVersionOut
from pareeksha.simulation.models import CallResult, CallSpec
from pareeksha.simulation.text_runner import run_text_call
from tests.unit.simulation.simfakes import ScriptedCaller, persona, scenario

KEY = "sk-secret-key-123"
TOOL = {
    "name": "lookup",
    "description": "look up an account",
    "parameters": {"type": "object", "properties": {}},
    "mock": {"mode": "static", "result": {"balance": 100}},
}


class FakeChat:
    """Returns the scripted replies in order; an Exception item is raised. Repeats the last."""

    def __init__(self, script: Sequence[ChatReply | Exception]) -> None:
        self.script = list(script)
        self.seen: list[list[AgentMessage]] = []

    async def chat(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolSpec],
        *,
        model: str,
        temperature: float,
        timeout_s: float = 60.0,
    ) -> ChatReply:
        """Record ``messages`` and return the next scripted reply (raised if an exception)."""
        self.seen.append(list(messages))
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        return item


def text(t: str, tokens: tuple[int, int] = (5, 3)) -> ChatReply:
    return ChatReply(t, (), tokens[0], tokens[1], 7)


def tools_reply(*calls: ToolCallReq) -> ChatReply:
    return ChatReply("", tuple(calls), 4, 2, 7)


def call(name: str = "lookup", raw: str = "{}", args: dict[str, Any] | None = None) -> ToolCallReq:
    """A ``ToolCallReq`` for tool ``name`` with the given raw and parsed arguments."""
    return ToolCallReq(f"id-{name}", name, args if args is not None else {}, raw)


def make(
    *, tools: bool = True, rounds: int = 3, scenario_over: dict[str, Any] | None = None
) -> CallSpec:
    """A prompt agent's ``CallSpec`` with the ``lookup`` tool (unless ``tools`` is false).

    ``rounds`` sets ``max_tool_rounds``; ``scenario_over`` overrides scenario fields.
    """
    version = PromptVersionOut.model_validate(
        {
            "id": uuid.uuid4(),
            "agent_id": uuid.uuid4(),
            "version": 1,
            "content_hash": "h",
            "created_at": "2026-11-06T00:00:00Z",
            "system_prompt": "You are a helpful agent.",
            "provider": "openai",
            "model": "gpt-x",
            "tools": [TOOL] if tools else [],
            "max_tool_rounds": rounds,
        }
    )
    return CallSpec(
        call_id=uuid.uuid4(),
        agent=AgentTarget(
            agent_id=version.agent_id,
            adapter="prompt",
            endpoint_url="",
            adapter_config={"prompt_version": version.model_dump(mode="json")},
            adapter_secrets={"api_key": KEY},
        ),
        persona=persona(),
        scenario=scenario(**(scenario_over or {})),
        profile=get_profile("clean_16k"),
        max_call_seconds=60,
    )


async def run(
    spec: CallSpec, lines: Sequence[Any], chat: FakeChat, clock: Any = None
) -> CallResult:
    """Run ``spec`` with a scripted caller saying ``lines`` and the fake chat provider."""
    kw: dict[str, Any] = {"clock": clock} if clock else {}
    return await run_text_call(spec, caller=ScriptedCaller(lines), chat=chat, **kw)


async def test_plain_conversation_records_turns() -> None:
    """Caller and agent lines alternate as indexed turns until ``max_turns``."""
    spec = make(scenario_over={"max_turns": 2})
    res = await run(spec, ["hi", "bye"], FakeChat([text("hello"), text("goodbye")]))
    assert [(t.idx, t.speaker, t.text) for t in res.turns] == [
        (0, "caller", "hi"),
        (1, "agent", "hello"),
        (2, "caller", "bye"),
        (3, "agent", "goodbye"),
    ]
    assert res.turns[1].glass_box_text == "hello"
    assert res.glass_box and res.end_reason == "max_turns"


async def test_tool_call_recorded_with_mock_result() -> None:
    """A tool call is recorded with its mock result and answered with a tool message."""
    chat = FakeChat([tools_reply(call(args={"a": 1})), text("you have 100")])
    res = await run(make(), ["balance?"], chat)
    [rec] = res.tool_calls
    assert (rec.seq, rec.name, rec.arguments, rec.result) == (
        0,
        "lookup",
        {"a": 1},
        {"balance": 100},
    )
    assert rec.turn_idx == 1 == res.turns[1].idx
    tool_msg = chat.seen[1][-1]
    assert tool_msg.role == "tool" and tool_msg.tool_call_id == "id-lookup"


async def test_assistant_message_reuses_tool_call_objects() -> None:
    """The assistant message passes the provider's own ``ToolCallReq`` objects back."""
    tc = call()
    chat = FakeChat([tools_reply(tc), text("ok")])
    await run(make(), ["x"], chat)
    assert chat.seen[1][-2].tool_calls[0] is tc


async def test_scenario_mock_override_used() -> None:
    """A scenario's ``mock_result`` replaces the tool's own mock."""
    over = {"expected_tool_calls": [{"name": "lookup", "mock_result": {"balance": 5}}]}
    chat = FakeChat([tools_reply(call()), text("5")])
    res = await run(make(scenario_over=over), ["x"], chat)
    assert res.tool_calls[0].result == {"balance": 5}


async def test_tool_round_limit_ends_agent_silent() -> None:
    """An agent that only calls tools ends ``agent_silent`` after ``max_tool_rounds``."""
    chat = FakeChat([tools_reply(call())])  # forever
    res = await run(make(rounds=2), ["x", "y"], chat)
    assert res.end_reason == "agent_silent"
    assert len(chat.seen) == 2
    assert any(e.type == "tool_round_limit" for e in res.events)


async def test_invalid_arguments_continue_call() -> None:
    """Unparseable arguments get ``invalid_arguments`` and the call goes on."""
    chat = FakeChat([tools_reply(call(raw="{oops", args={"_raw": "{oops"})), text("sorry")])
    res = await run(make(scenario_over={"max_turns": 1}), ["x"], chat)
    assert res.tool_calls[0].arguments == {"_raw": "{oops"}
    assert res.tool_calls[0].result == {"error": "invalid_arguments"}
    assert [t.speaker for t in res.turns] == ["caller", "agent"]


async def test_provider_error_first_turn_connect_failed() -> None:
    """A provider error before any agent turn ends the call ``connect_failed``."""
    res = await run(make(), ["x"], FakeChat([AgentLLMError("provider returned HTTP 401: nope")]))
    assert res.end_reason == "connect_failed"
    assert res.error == "provider returned HTTP 401: nope"


async def test_provider_error_later_infra_error_without_key() -> None:
    """A later provider error ends ``infra_error`` and the result never contains the key."""
    chat = FakeChat([text("hello"), AgentLLMError("provider returned HTTP 503: down")])
    res = await run(make(), ["x", "y"], chat)
    assert res.end_reason == "infra_error"
    assert res.error is not None and KEY not in res.error
    assert KEY not in res.model_dump_json()


async def test_max_turns() -> None:
    """The call stops after ``max_turns`` caller lines."""
    res = await run(make(scenario_over={"max_turns": 2}), ["a", "b", "c"], FakeChat([text("r")]))
    assert res.end_reason == "max_turns"
    assert sum(t.speaker == "caller" for t in res.turns) == 2


async def test_caller_end_call() -> None:
    """A caller hanging up before running out of patience ends ``goal_achieved``."""
    from pareeksha.simulation.runtime import CallerLine

    lines = ["hi", CallerLine("thanks, bye", end_call=True)]
    res = await run(make(), lines, FakeChat([text("hello")]))
    assert res.end_reason == "goal_achieved"
    assert res.turns[-1].speaker == "caller" and res.turns[-1].text == "thanks, bye"


async def test_usage_events_recorded() -> None:
    """Each model request logs an ``agent_llm_usage`` event with tokens, latency and model."""
    chat = FakeChat([tools_reply(call()), text("done", (11, 22))])
    res = await run(make(), ["x"], chat)
    usage = [e for e in res.events if e.type == "agent_llm_usage"]
    assert len(usage) == 2
    assert usage[1].data == {
        "input_tokens": 11,
        "output_tokens": 22,
        "latency_ms": 7,
        "model": "gpt-x",
    }
