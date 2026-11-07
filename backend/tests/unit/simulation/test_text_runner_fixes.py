"""Text-runner review fixes: simulated-tool usage tag, retrieval latency, repeated {{context}}."""

from __future__ import annotations

import itertools
from typing import Any

from pareeksha.agent_llm.base import ChatProvider
from pareeksha.rag.report import CallData, EntryModels, summarize
from pareeksha.rag.retriever import RetrievalOutcome, Retriever
from pareeksha.schemas.rag import RagConfig
from tests.unit.simulation.test_text_runner import FakeChat, call, make, text, tools_reply
from tests.unit.simulation.test_text_runner_rag import KB, retr, run, system_of, with_rag


async def test_simulated_tool_results_are_tagged_and_left_out_of_cost() -> None:
    spec = make(tools=True)
    spec.agent.adapter_config["prompt_version"]["tools"][0]["mock"] = {"mode": "simulated"}
    chat = FakeChat(
        [tools_reply(call("lookup")), text('{"balance": 5}', (50, 20)), text("done", (10, 4))]
    )
    result = await run(spec, ["what is my balance"], chat)
    usage = [e.data for e in result.events if e.type == "agent_llm_usage"]
    assert [u.get("purpose") for u in usage] == [None, "tool_simulation", None]
    assert result.tool_calls[0].result == {"balance": 5}

    events = [e.model_dump(mode="json") for e in result.events]
    row = summarize(
        "x",
        "no_rag",
        [CallData(events=events)],
        run_id=None,
        run_status=None,
        prices={},
        models=EntryModels(),
    ).row
    # 4 + 10 input and 2 + 4 output tokens of the agent turns; the simulator's 50 / 20 is excluded
    assert row["tokens_per_conversation"]["agent_input"] == 14
    assert row["tokens_per_conversation"]["agent_output"] == 6


async def test_retrieval_total_leaves_out_the_cold_load() -> None:
    """The runner's wall clock saw a 5 s model load; the retriever's own total does not."""

    class Cold(Retriever):
        async def retrieve(self, query: str, *, chat: ChatProvider | None) -> RetrievalOutcome:
            return RetrievalOutcome([], "ctx", [query], {"embed_ms": 3, "total_ms": 7})

    ticks = itertools.count(0, 1.0)  # every clock() read is 1 s later
    spec = with_rag(make(tools=False))
    cold = Cold(RagConfig(kb_id=KB), spec.agent.adapter_config["rag"]["index"], retr(spec).embedder)
    chat = FakeChat([text("ok")])
    result = await _timed(spec, chat, cold, lambda: next(ticks))
    assert result.retrievals[0].timings == {"embed_ms": 3, "total_ms": 7}


async def _timed(spec: Any, chat: FakeChat, retriever: Retriever, clock: Any) -> Any:
    from pareeksha.simulation.text_runner import run_text_call
    from tests.unit.simulation.simfakes import ScriptedCaller

    return await run_text_call(
        spec, caller=ScriptedCaller(["hi"]), chat=chat, clock=clock, retriever=retriever
    )


async def test_every_context_placeholder_gets_the_same_context() -> None:
    spec = with_rag(make(tools=False), "Top: {{context}}\nBottom: {{context}}")
    chat = FakeChat([text("ok")])
    await run(spec, ["when is my refund"], chat, retr(spec))
    ctx = "[1] (source: faq.txt)\nRefunds take seven days."
    assert system_of(chat) == f"Top: {ctx}\nBottom: {ctx}"
