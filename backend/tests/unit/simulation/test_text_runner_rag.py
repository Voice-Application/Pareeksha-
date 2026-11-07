"""RAG in the text runner: placement, per-turn recording, failure handling (no network, no DB)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from pareeksha.agent_llm.base import ChatProvider
from pareeksha.rag.retriever import Retriever
from pareeksha.schemas.rag import RagConfig
from pareeksha.simulation.models import CallResult, CallSpec
from pareeksha.simulation.text_runner import run_text_call
from tests.unit.rag.test_retriever import FakeEmbedder, make_index
from tests.unit.simulation.simfakes import ScriptedCaller
from tests.unit.simulation.test_text_runner import FakeChat, make, text

KB = uuid.uuid4()
KB_TEXT = "\n\n# a.txt\nRefunds take seven days."


def with_rag(spec: CallSpec, prompt: str | None = None, **rag: Any) -> CallSpec:
    cfg = RagConfig.model_validate(
        {"kb_id": KB, "method": "dense", "top_k": 1, "candidate_k": 3, **rag.pop("config", {})}
    )
    pv = spec.agent.adapter_config["prompt_version"]
    if prompt is not None:
        pv["system_prompt"] = prompt
    spec.agent.adapter_config["rag"] = {
        "config": cfg.model_dump(mode="json"),
        "index_id": str(uuid.uuid4()),
        "kb_id": str(KB),
        "local_only": False,
        "index": make_index(),
        **rag,
    }
    return spec


def retr(spec: CallSpec) -> Retriever:
    cfg = RagConfig.model_validate(spec.agent.adapter_config["rag"]["config"])
    return Retriever(cfg, spec.agent.adapter_config["rag"]["index"], FakeEmbedder(), model="m")


async def run(
    spec: CallSpec,
    lines: Sequence[str],
    chat: FakeChat,
    retriever: Retriever | None = None,
) -> CallResult:
    return await run_text_call(spec, caller=ScriptedCaller(lines), chat=chat, retriever=retriever)


def system_of(chat: FakeChat, call_no: int = 0) -> str:
    return chat.seen[call_no][0].content


async def test_context_placeholder_replaced() -> None:
    spec = with_rag(make(tools=False), "Answer from:\n{{context}}\nBe brief.")
    chat = FakeChat([text("ok")])
    await run(spec, ["when is my refund"], chat, retr(spec))
    sys = system_of(chat)
    assert "{{context}}" not in sys and "[1] (source: faq.txt)\nRefunds take seven days." in sys
    assert "Retrieved context:" not in sys


async def test_context_appended_without_placeholder() -> None:
    spec = with_rag(make(tools=False))
    chat = FakeChat([text("ok")])
    await run(spec, ["when is my refund"], chat, retr(spec))
    assert system_of(chat) == (
        "You are a helpful agent.\n\nRetrieved context:\n"
        "[1] (source: faq.txt)\nRefunds take seven days."
    )


async def test_full_context_mode() -> None:
    spec = with_rag(
        make(tools=False),
        config={"mode": "full_context"},
        full_context_text=KB_TEXT,
        index_id=None,
    )
    chat = FakeChat([text("ok")])
    result = await run(spec, ["hello"], chat)
    assert system_of(chat).endswith("Retrieved context:\n" + KB_TEXT)
    (rec,) = result.retrievals
    assert rec.index_id is None and rec.context_chars == len(KB_TEXT) and rec.results == []


async def test_retrieval_recorded_per_turn() -> None:
    spec = with_rag(make(tools=False))
    chat = FakeChat([text("one"), text("two")])
    result = await run(spec, ["refund?", "loan?"], chat, retr(spec))
    assert [r.turn_idx for r in result.retrievals] == [1, 3]
    assert [r.query for r in result.retrievals] == ["refund?", "loan?"]
    assert [t.idx for t in result.turns if t.speaker == "agent"] == [1, 3]
    assert result.retrievals[0].results[0]["filename"] == "faq.txt"
    assert any(e.type == "retrieval" and e.data["n_results"] == 1 for e in result.events)
    assert "Loans need KYC." in system_of(chat, 1)  # refreshed each turn


async def test_retrieval_failure_continues() -> None:
    class Boom(Retriever):
        async def retrieve(self, query: str, *, chat: ChatProvider | None) -> Any:
            raise RuntimeError("index offline")

    spec = with_rag(make(tools=False), "Use {{context}} well.")
    boom = Boom(RagConfig(kb_id=KB), spec.agent.adapter_config["rag"]["index"], FakeEmbedder())
    chat = FakeChat([text("fine")])
    result = await run(spec, ["hi"], chat, boom)
    assert result.end_reason != "infra_error" and result.retrievals == []
    assert system_of(chat) == "Use  well."
    assert [e.data["error"] for e in result.events if e.type == "retrieval_failed"] == [
        "index offline"
    ]
    assert any(t.speaker == "agent" and t.text == "fine" for t in result.turns)


async def test_off_mode_unchanged() -> None:
    spec = make(tools=False)
    spec.agent.adapter_config["prompt_version"]["system_prompt"] = "Keep {{context}} as is."
    chat = FakeChat([text("ok")])
    result = await run(spec, ["hi"], chat)
    assert system_of(chat) == "Keep {{context}} as is." and result.retrievals == []
    assert not any(e.type.startswith("retrieval") for e in result.events)
