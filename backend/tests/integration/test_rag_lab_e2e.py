"""The RAG lab end to end: KB -> indexes -> questions -> matrix -> runs -> metrics -> report.

Real app and Postgres; the embedder, the agent model, the simulated caller and the judge are
scripted. The workers' handlers are driven directly (no Kafka), as in ``test_prompt_agent_e2e``.
"""

from __future__ import annotations

import json
import re
import zlib
from collections.abc import AsyncIterator, Sequence
from math import sqrt
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.events.consumer import Ctx
from pareeksha.events.runtime import Database
from pareeksha.events.schemas import CallCompleted, CallRequested, KbIndexRequested, make_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.llm.base import JSONCompletionRequest, JSONCompletionResult
from pareeksha.llm.client import LLMClient
from pareeksha.llm.config import LLMSettings
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.rag import retriever as retriever_mod
from pareeksha.rag.embeddings import EmbedResult
from pareeksha.simulation.runtime import CallerLine
from pareeksha.storage.blob import LocalBlobStore
from pareeksha.workers import evaluator, simulator
from pareeksha.workers.indexer import handle_index_requested
from tests.conftest import Tenant
from tests.integration.audit_support import transaction
from tests.integration.domain import outbox_for
from tests.integration.eval_support import seed_rubric
from tests.integration.runs_support import API, make_fixture, plan_in_db, settings_for
from tests.unit.evaluation.fakes import ScriptedProvider, judge_json
from tests.unit.simulation.simfakes import ScriptedCaller
from tests.unit.simulation.test_text_runner import FakeChat, text

KB = f"{API}/knowledge-bases"
# Uploads write blobs: always use the temp-dir store, never the repo's backend/data.
pytestmark = pytest.mark.usefixtures("blobs")

REFUNDS = (
    "Refund policy. Refunds are processed within 7 business days of approval. "
    "The money goes back to the original payment method. Cash refunds are not offered. "
    "If a refund is delayed beyond the stated period, write to the support team with the "
    "order number and we will escalate it to the payments desk on the same day."
)
DELIVERY = (
    "Delivery policy. Standard delivery takes 3 to 5 working days across India. "
    "Express delivery is available only in metro cities and costs an extra Rs 99. "
    "Orders placed after 6 pm are dispatched on the next working day. "
    "Tracking links are sent by SMS as soon as the courier picks up the parcel."
)
QUESTIONS = [
    ("How many business days do refunds take to process?", "7 business days"),
    ("How long does standard delivery take?", "3 to 5 working days"),
    ("What is the warranty on laptops?", ""),
]
CSV = (
    "question,expected_answer,source_document,source_quote\n"
    f'"{QUESTIONS[0][0]}",7 business days,refunds.txt,'
    '"Refunds are processed within 7 business days of approval"\n'
    f'"{QUESTIONS[1][0]}",3 to 5 working days,delivery.txt,'
    '"Standard delivery takes 3 to 5 working days"\n'
    f"{QUESTIONS[2][0]},,,\n"
)
MADE_UP = "Refunds take 30 days and delivery takes 2 days."


class BowEmbedder:
    """Deterministic bag-of-words hash vectors, so similar texts really are close."""

    async def embed(self, texts: Sequence[str], *, kind: str) -> EmbedResult:
        vecs: list[list[float]] = []
        for t in texts:
            v = [0.0] * 64
            for w in re.findall(r"\w+", t.lower()):
                v[zlib.crc32(w.encode()) % 64] += 1.0
            norm = sqrt(sum(x * x for x in v)) or 1.0
            vecs.append([x / norm for x in v])
        return EmbedResult(vecs, input_tokens=len(texts), latency_ms=1)


class AgentChat(FakeChat):
    """No context: makes a fact up. With context: answers from it (or admits it does not know)."""

    def __init__(self) -> None:
        super().__init__([text("unused")])

    async def chat(self, messages: Any, tools: Any, **kw: Any) -> Any:
        self.seen.append(list(messages))
        system, question = messages[0].content, messages[-1].content
        if "Retrieved context:" not in system:
            return text(MADE_UP)
        if "warranty" in question:
            return text("I do not know that from the documents.")
        body = system.split("Retrieved context:", 1)[1].strip()
        return text(f"According to our policy: {body[:120]}")


class RagJudge(ScriptedProvider):
    """Rubric calls get the stock verdict; RAG calls are decided by what the answer says."""

    def __init__(self) -> None:
        super().__init__([])

    async def complete_json(self, request: JSONCompletionRequest) -> JSONCompletionResult:
        content = request.messages[0].content
        if "claims" in json.dumps(request.json_schema) or "claims" in content:
            made_up = MADE_UP in content
            reply = json.dumps(
                {
                    "claims": [
                        {
                            "text": "a policy claim",
                            "supported": not made_up,
                            "evidence": None if made_up else 0,
                        }
                    ]
                    if "do not know" not in content
                    else [],
                    "answer_correct": not made_up,
                    "refused": "do not know" in content,
                }
            )
        else:
            reply = judge_json()
        self.replies = [reply]
        return await super().complete_json(request)


class OneQuestionCaller(ScriptedCaller):
    """Asks the scenario's question, then hangs up."""

    def __init__(self) -> None:
        super().__init__([])

    async def next_line(self, persona: Any, scenario: Any, history: Any, turn_number: int) -> Any:
        if not history:
            return CallerLine(scenario.title)
        return CallerLine("okay thank you", end_call=True)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())


@pytest.fixture
async def workers(database_url: str, tmp_path: Any) -> AsyncIterator[Database]:
    settings = settings_for(database_url)
    db = Database(settings)
    usage = ApiUsageSink(settings)
    simulator.configure(db=db, usage=usage, blobs=LocalBlobStore(tmp_path))
    yield db
    simulator.configure()
    evaluator.set_client(None)
    await db.close()
    await usage.close()


async def _build_index(
    api: AsyncClient,
    tenant: Tenant,
    factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
    kb_id: str,
    chunking: dict[str, Any],
) -> None:
    accepted = await api.post(
        f"{KB}/{kb_id}/indexes",
        json={"chunking": chunking, "embedding": {}},
        headers=tenant.admin,
    )
    assert accepted.status_code == 202, accepted.text
    index_id = accepted.json()["id"]
    (env,) = await outbox_for(factory, "index_id", index_id)
    assert isinstance(env.payload, KbIndexRequested)
    ctx = Ctx(tx=pg, group="indexer", topic=env.topic.value, partition=0, offset=0, attempt=1)
    async with pg.transaction():
        await handle_index_requested(env, ctx, lambda _cfg, _key: BowEmbedder())  # type: ignore[arg-type]
    done = await api.get(f"{KB}/{kb_id}/indexes/{index_id}", headers=tenant.read)
    assert done.json()["status"] == "ready", done.text


async def _simulate_and_evaluate(
    database_url: str, workers: Database, monkeypatch: pytest.MonkeyPatch, run_id: str
) -> None:
    requests = [
        o.payload
        for o in await plan_in_db(database_url, run_id)
        if isinstance(o.payload, CallRequested)
    ]
    assert len(requests) == len(QUESTIONS)
    monkeypatch.setattr(simulator, "build_chat_provider", lambda *a, **k: AgentChat())
    monkeypatch.setattr(simulator, "_caller", OneQuestionCaller())
    usage = ApiUsageSink(settings_for(database_url))
    judge = LLMClient(
        RagJudge(), LLMSettings(_env_file=None, deepseek_api_key="k"), usage_sink=usage
    )
    evaluator.set_client(judge, usage, workers)
    try:
        for req in requests:
            env = make_envelope(req, producer="planner", correlation_id=run_id)
            async with transaction(database_url) as ctx:
                (out,) = await simulator.on_call_requested(env, ctx)
            assert isinstance(out.payload, CallCompleted)
            done = make_envelope(out.payload, producer="simulator", correlation_id=run_id)
            async with transaction(database_url) as ctx:
                await evaluator.on_call_completed(done, ctx)
    finally:
        await usage.close()


async def test_rag_lab_flow(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
    workers: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fx = await make_fixture(api, tenant, 0, 1, 1)
    with psycopg.connect(libpq_url(database_url), autocommit=True) as conn:
        seed_rubric(conn)
    monkeypatch.setattr(retriever_mod, "build_embedder", lambda cfg, **kw: BowEmbedder())

    # 1. a KB with two documents
    kb = await api.post(KB, json={"name": "shop-faq"}, headers=tenant.admin)
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]
    for name, body in (("refunds.txt", REFUNDS), ("delivery.txt", DELIVERY)):
        up = await api.post(
            f"{KB}/{kb_id}/documents", files={"file": (name, body.encode())}, headers=tenant.admin
        )
        assert up.status_code == 201, up.text

    # 2. two indexes with different chunking
    rec = {"strategy": "recursive", "size": 400, "overlap": 50}
    fixed = {"strategy": "fixed", "size": 800, "overlap": 0}
    await _build_index(api, tenant, session_factory, pg, kb_id, rec)
    await _build_index(api, tenant, session_factory, pg, kb_id, fixed)

    # 3. the agent, whose prompt has no {{context}}: the context is appended to it
    agent = await api.post(
        f"{API}/agents",
        json={"name": "shop-bot", "adapter": "prompt", "adapter_secrets": {"api_key": "sk-x"}},
        headers=tenant.admin,
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]
    v = await api.post(
        f"{API}/agents/{agent_id}/prompt-versions",
        json={
            "system_prompt": "Answer shop questions.",
            "provider": "openai",
            "model": "gpt-x",
        },
        headers=tenant.admin,
    )
    assert v.status_code == 201, v.text

    # 4. three ground-truth questions: two answerable, one not
    imp = await api.post(
        f"{KB}/{kb_id}/questions:import",
        data={"agent_id": agent_id},
        files={"file": ("q.csv", CSV.encode(), "text/csv")},
        headers=tenant.admin,
    )
    assert imp.status_code == 200, imp.text
    assert imp.json() == {"created": 3, "unmatched": []}
    scenarios = await api.get(
        f"{API}/scenarios", params={"agent_id": agent_id, "tag": "rag"}, headers=tenant.read
    )
    scenario_ids = [s["id"] for s in scenarios.json()["items"]]
    assert len(scenario_ids) == 3

    # 5. the matrix: two configs plus both baselines
    cfgs = [
        {"kb_id": kb_id, "method": "bm25", "top_k": 2, "chunking": rec, "label": "bm25-rec400"},
        {"kb_id": kb_id, "method": "dense", "top_k": 2, "chunking": fixed, "label": "dense-fix800"},
    ]
    matrix = await api.post(
        f"{API}/rag-matrices",
        json={
            "agent_id": agent_id,
            "configs": cfgs,
            "scenario_ids": scenario_ids,
            "persona_ids": fx.persona_ids,
            "noise_profile_ids": fx.noise_profile_ids,
        },
        headers=tenant.admin,
    )
    assert matrix.status_code == 201, matrix.text
    entries = matrix.json()["entries"]
    assert [e["kind"] for e in entries] == ["no_rag", "full_context", "rag", "rag"]

    # 6. simulate and evaluate every run
    for e in entries:
        await _simulate_and_evaluate(database_url, workers, monkeypatch, e["run_id"])

    # 7. the report
    rep = await api.get(f"{API}/rag-matrices/{matrix.json()['id']}/report", headers=tenant.read)
    assert rep.status_code == 200, rep.text
    report = rep.json()
    assert len(report["rows"]) == 4
    rows = {r["label"]: r for r in report["rows"]}
    no_rag = rows["No RAG"]
    assert no_rag["n_calls"] == 3
    assert no_rag["generation"]["hallucination_rate"] > 0  # it made a fact up
    for label in ("bm25-rec400", "dense-fix800"):
        assert rows[label]["retrieval"]["hit_rate"] > 0, rows[label]
        assert rows[label]["generation"]["hallucination_rate"] == 0
    assert report["recommendation"] == {
        "label": None,
        "reason": "not enough ground-truth questions (2 < 10)",
    }

    # 8. any two configs compare with the ordinary run comparison
    cmp = await api.get(
        f"{API}/runs/compare",
        params={"base": entries[0]["run_id"], "head": entries[2]["run_id"]},
        headers=tenant.read,
    )
    assert cmp.status_code == 200, cmp.text
    assert len(cmp.json()["cells"]) == 3
