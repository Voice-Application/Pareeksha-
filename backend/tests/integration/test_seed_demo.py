"""First-run demo data (``pareeksha.seed.demo``) on an empty, migrated Postgres: what the web app
shows after ``python -m pareeksha.seed`` (prompt compare, RAG report), idempotence, and that the
precomputed retrievals match the index the indexer worker builds from the seeded documents."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.main import app
from pareeksha.db.models import (
    Agents,
    Calls,
    Evaluations,
    KbChunks,
    KbIndexes,
    RagMatrices,
    RagMetrics,
    Retrievals,
    Scenarios,
    TestRuns,
)
from pareeksha.db.session import get_session_factory
from pareeksha.events.consumer import Ctx
from pareeksha.events.schemas import KbIndexRequested
from pareeksha.events.settings import libpq_url
from pareeksha.rag.embeddings import EmbedResult
from pareeksha.seed.demo import DEMO_JUDGE_MODEL
from pareeksha.seed.runner import seed_database
from pareeksha.workers.indexer import handle_index_requested
from tests.conftest import bearer
from tests.integration.domain import outbox_for

Factory = async_sessionmaker[AsyncSession]
API = "/api/v1"
PROMPT_AGENT = "Demo · Sahay EMI helpdesk"
RAG_AGENT = "Demo · Sahay FAQ assistant"


@pytest.fixture(autouse=True)
def _no_pinned_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAREEKSHA_API_KEY", raising=False)


@pytest.fixture
def factory(fresh_session_factory: Factory) -> Factory:
    """A private, empty database per test (the shared one may already be seeded)."""
    return fresh_session_factory


def _url(factory: Factory) -> str:
    bind = factory.kw["bind"]
    return libpq_url(str(bind.url.render_as_string(hide_password=False)))


@pytest.fixture
async def seeded(factory: Factory) -> AsyncIterator[tuple[AsyncClient, dict[str, str]]]:
    """Seed once, then the real app over ASGI with the demo key."""
    result = await seed_database(factory)
    assert result.demo_key is not None
    app.dependency_overrides[get_session_factory] = lambda: factory
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            yield api, bearer(result.demo_key)
    finally:
        app.dependency_overrides.pop(get_session_factory, None)


async def _count(factory: Factory, model: type) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def _agent(api: AsyncClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    items = (await api.get(f"{API}/agents?limit=200", headers=headers)).json()["items"]
    return next(a for a in items if a["name"] == name)


async def test_demo_is_created_once_and_never_overwritten(factory: Factory) -> None:
    first = await seed_database(factory)
    assert first.created["demo_agents"] == 2
    assert first.created["prompt_versions"] == 3  # EMI v1 + v2, FAQ v1
    assert first.created["demo_scenarios"] == 4 + 14
    assert first.created["demo_runs"] == 2 + 5  # v1, v2 and the five matrix entries
    assert first.created["knowledge_bases"] == 1 and first.created["kb_documents"] == 4
    assert first.created["kb_indexes"] == 1 and first.created["rag_matrices"] == 1
    assert first.created["price_overrides"] == 1
    calls = await _count(factory, Calls)
    assert calls == 4 * 2 * 2 + 14 * 5

    # a user's edit survives, and nothing is added twice
    async with factory() as session, session.begin():
        kb = (await session.scalars(select(RagMatrices))).one()
        kb.entries = []
    second = await seed_database(factory)
    assert second.created == {}
    assert second.existing["demo_agents"] == 2 and second.existing["knowledge_bases"] == 1
    assert await _count(factory, Calls) == calls
    async with factory() as session:
        assert (await session.scalars(select(RagMatrices))).one().entries == []


async def test_prompt_compare_shows_the_v2_regression(
    seeded: tuple[AsyncClient, dict[str, str]], factory: Factory
) -> None:
    api, headers = seeded
    agent = await _agent(api, headers, PROMPT_AGENT)
    assert agent["adapter"] == "prompt" and agent["endpoint_url"] == f"prompt://{agent['id']}"
    versions = (
        await api.get(f"{API}/agents/{agent['id']}/prompt-versions", headers=headers)
    ).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert {t["name"] for t in agent["expected_tools"]} == {
        "get_loan_details",
        "create_payment_link",
        "transfer_to_agent",
    }
    async with factory() as session:
        runs = {
            r.name: r
            for r in await session.scalars(select(TestRuns).where(TestRuns.agent_id == agent["id"]))
        }
    v1 = runs["Demo · EMI helpdesk v1 (baseline)"]
    v2 = runs["Demo · EMI helpdesk v2 (shorter prompt)"]
    assert v1.status == v2.status == "completed"
    r = await api.get(
        f"{API}/runs/compare", params={"base": str(v1.id), "head": str(v2.id)}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["base_prompt_version"], body["head_prompt_version"]) == (1, 2)
    assert len(body["cells"]) == 8
    assert body["summary"]["regressed"] == 6 and body["summary"]["improved"] == 2
    assert sum(c["newly_failing"] for c in body["cells"]) == 6

    run = (await api.get(f"{API}/runs/{v2.id}", headers=headers)).json()
    assert run["summary"]["pass_rate"] == 0.25 and run["summary"]["critical_failures"] == 6

    # a v2 call: tool calls checked by the real deterministic checks, a precomputed evaluation
    cell = next(c for c in body["cells"] if "Disputes" in c["scenario"])
    call = (await api.get(f"{API}/calls/{cell['head_call_ids'][0]}", headers=headers)).json()
    checks = {(c["check_type"], c["check_key"]): c["passed"] for c in call["checks"]}
    assert checks[("tool_calls_expected", "transfer_to_agent")] is False
    assert checks[("tool_calls_expected", "not_called:create_payment_link")] is False
    assert checks[("no_unexpected_tool", "get_loan_details#1")] is False
    assert [t["name"] for t in call["tool_calls"]] == ["get_loan_details", "create_payment_link"]
    assert call["evaluation"]["judge_model"] == DEMO_JUDGE_MODEL
    assert call["evaluation"]["passed"] is False
    assert "escalation_error" in call["evaluation"]["failure_types"]


async def test_rag_report_is_populated(
    seeded: tuple[AsyncClient, dict[str, str]], factory: Factory
) -> None:
    api, headers = seeded
    matrices = (await api.get(f"{API}/rag-matrices", headers=headers)).json()
    items = matrices["items"] if isinstance(matrices, dict) else matrices
    (matrix,) = items
    r = await api.get(f"{API}/rag-matrices/{matrix['id']}/report", headers=headers)
    assert r.status_code == 200, r.text
    report = r.json()
    rows = {row["kind"] if row["kind"] != "rag" else row["label"]: row for row in report["rows"]}
    assert len(report["rows"]) == 5
    assert all(row["n_calls"] == 14 for row in report["rows"])
    rag_rows = [row for row in report["rows"] if row["kind"] == "rag"]
    assert [row["label"].split(" ·")[0] for row in rag_rows] == ["hybrid+rerank", "hybrid", "bm25"]
    hit = [row["retrieval"]["hit_rate"] for row in rag_rows]
    assert hit == [1.0, 11 / 12, 0.75]
    assert all(row["n_questions_with_truth"] == 12 for row in rag_rows)
    assert rows["no_rag"]["retrieval"]["hit_rate"] is None
    halluc = {k: v["generation"]["hallucination_rate"] for k, v in rows.items()}
    assert halluc["no_rag"] > halluc["full_context"] > halluc[rag_rows[0]["label"]]
    # costs in rupees, retrieval cheaper than stuffing the whole KB into the prompt
    assert all(row["cost_per_conversation_inr"] is not None for row in report["rows"])
    assert all((row["token_savings_vs_full_context_pct"] or 0) > 20 for row in rag_rows)
    assert rag_rows[0]["latency_ms"]["rerank_p50"] is not None
    assert report["recommendation"]["label"] == rag_rows[0]["label"]

    # the questions are real ground truth: their spans point into the seeded documents
    agent = await _agent(api, headers, RAG_AGENT)
    async with factory() as session:
        questions = list(
            await session.scalars(select(Scenarios).where(Scenarios.agent_id == agent["id"]))
        )
        assert await session.scalar(select(func.count()).select_from(RagMetrics)) == 70
        judges = set(await session.scalars(select(Evaluations.judge_model)))
    assert judges == {DEMO_JUDGE_MODEL}
    answerable = [q for q in questions if q.rag_expectation and q.rag_expectation["answerable"]]
    assert len(questions) == 14 and len(answerable) == 12
    kb_id = matrix["kb_id"]
    docs = (await api.get(f"{API}/knowledge-bases/{kb_id}/documents", headers=headers)).json()
    doc_items = docs["items"] if isinstance(docs, dict) else docs
    assert len(doc_items) == 4
    texts = {
        d["id"]: (
            await api.get(f"{API}/knowledge-bases/{kb_id}/documents/{d['id']}", headers=headers)
        ).json()["text"]
        for d in doc_items
    }
    for q in answerable:
        exp = q.rag_expectation
        assert exp is not None
        start, end = exp["source_span"]
        assert texts[exp["source_document_id"]][start:end].strip()


async def test_index_is_left_to_the_indexer_and_matches_the_precomputed_chunks(
    factory: Factory,
) -> None:
    await seed_database(factory)
    async with factory() as session:
        index = (await session.scalars(select(KbIndexes))).one()
        seeded_hits = {
            (h["document_id"], h["start_char"], h["end_char"], h["text"])
            for r in await session.scalars(select(Retrievals.results))
            for h in r
        }
    assert index.status == "pending" and index.embedding["provider"] == "local"
    (env,) = await outbox_for(factory, "index_id", str(index.id))
    assert isinstance(env.payload, KbIndexRequested)

    class FakeEmbedder:
        async def embed(self, texts: Any, *, kind: str) -> EmbedResult:
            return EmbedResult([[1.0, 0.0] for _ in texts], input_tokens=len(texts), latency_ms=1)

    pg = await psycopg.AsyncConnection.connect(_url(factory), autocommit=True)
    try:
        ctx = Ctx(tx=pg, group="indexer", topic=env.topic.value, partition=0, offset=0, attempt=1)
        async with pg.transaction():
            await handle_index_requested(
                env,  # type: ignore[arg-type]
                ctx,
                lambda _cfg, _key: FakeEmbedder(),
            )
    finally:
        await pg.close()
    async with factory() as session:
        built = await session.get(KbIndexes, index.id)
        assert built is not None and built.status == "ready"
        chunks = {
            (str(c.document_id), c.start_char, c.end_char, c.text)
            for c in await session.scalars(select(KbChunks).where(KbChunks.index_id == index.id))
        }
        # the demo agents' version and the matrix pin the index the worker just built
        assert await session.scalar(select(func.count()).select_from(Agents)) == 3
    assert seeded_hits and seeded_hits <= chunks
