"""RAG matrices, report and pricing against the real app and Postgres (RAG lab Task 9)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient
from psycopg.types.json import Jsonb

from pareeksha.events.settings import libpq_url
from pareeksha.schemas.rag import RagConfig, index_key
from tests.conftest import Tenant
from tests.integration.runs_support import API, make_fixture

MATRICES = f"{API}/rag-matrices"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())


@dataclass
class Setup:
    agent_id: str
    kb_id: str
    project_id: uuid.UUID
    scenario_id: str
    persona_id: str
    noise_id: str
    url: str

    def cfg(self, **kw: Any) -> dict[str, Any]:
        return {"kb_id": self.kb_id, "method": "bm25", "top_k": 3, **kw}

    def body(self, configs: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "configs": configs,
            "scenario_ids": [self.scenario_id],
            "persona_ids": [self.persona_id],
            "noise_profile_ids": [self.noise_id],
            **kw,
        }


async def setup(api: AsyncClient, tenant: Tenant, database_url: str, chars: int = 5000) -> Setup:
    fx = await make_fixture(api, tenant, 0, 1, 1)
    kb = await api.post(
        f"{API}/knowledge-bases", json={"name": f"kb-{uuid.uuid4().hex[:8]}"}, headers=tenant.admin
    )
    assert kb.status_code == 201, kb.text
    agent = await api.post(
        f"{API}/agents",
        json={"name": "rag-bot", "adapter": "prompt", "adapter_secrets": {"api_key": "sk-x"}},
        headers=tenant.admin,
    )
    agent_id = agent.json()["id"]
    version = await api.post(
        f"{API}/agents/{agent_id}/prompt-versions",
        json={
            "system_prompt": "Answer using:\n{{context}}",
            "provider": "openai",
            "model": "m",
        },
        headers=tenant.admin,
    )
    assert version.status_code == 201, version.text
    scenario = await api.post(
        f"{API}/scenarios",
        json={
            "title": "refund",
            "caller_goal": "Ask about refunds.",
            "success_criteria": "ok",
            "max_turns": 2,
            "agent_id": agent_id,
        },
        headers=tenant.admin,
    )
    assert scenario.status_code == 201, scenario.text
    async with await psycopg.AsyncConnection.connect(
        libpq_url(database_url), autocommit=True
    ) as conn:
        cur = await conn.execute("SELECT project_id FROM agents WHERE id = %s", (agent_id,))
        row = await cur.fetchone()
        assert row is not None
        await conn.execute(
            "INSERT INTO kb_documents (kb_id, project_id, filename, mime, sha256, text, "
            "char_count, blob_key) VALUES (%s, %s, 'faq.txt', 'text/plain', %s, 'x', %s, 'k')",
            (kb.json()["id"], row[0], uuid.uuid4().hex, chars),
        )
    return Setup(
        agent_id,
        kb.json()["id"],
        row[0],
        scenario.json()["id"],
        fx.persona_ids[0],
        fx.noise_profile_ids[0],
        database_url,
    )


async def add_index(s: Setup, cfg: dict[str, Any], version: int, input_tokens: int = 0) -> None:
    rc = RagConfig.model_validate(cfg)
    async with await psycopg.AsyncConnection.connect(libpq_url(s.url), autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO kb_indexes (kb_id, project_id, version, index_key, chunking, embedding, "
            "status, chunk_count, stats) VALUES (%s, %s, %s, %s, %s, %s, 'ready', 1, %s)",
            (
                s.kb_id,
                s.project_id,
                version,
                index_key(rc),
                json.dumps(rc.chunking.model_dump(mode="json")),
                json.dumps(rc.embedding.model_dump(mode="json")),
                Jsonb({"input_tokens": input_tokens}),
            ),
        )


async def test_matrix_creates_runs_per_entry(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    s = await setup(api, tenant, database_url)
    a, b = s.cfg(label="bm25-3"), s.cfg(label="bm25-5", top_k=5)
    await add_index(s, a, 1)  # a and b share chunking+embedding, so one index serves both
    r = await api.post(MATRICES, json=s.body([a, b]), headers=tenant.admin)
    assert r.status_code == 201, r.text
    out = r.json()
    assert [e["label"] for e in out["entries"]] == ["No RAG", "Full context", "bm25-3", "bm25-5"]
    assert [e["kind"] for e in out["entries"]] == ["no_rag", "full_context", "rag", "rag"]
    for e in out["entries"]:
        run = await api.get(f"{API}/runs/{e['run_id']}", headers=tenant.read)
        assert run.status_code == 200 and run.json()["name"] == f"RAG · {e['label']}"
    ids = {e["run_id"] for e in out["entries"]}
    assert len(ids) == 4
    got = await api.get(f"{MATRICES}/{out['id']}", headers=tenant.read)
    assert got.json()["entries"] == out["entries"]
    listed = await api.get(MATRICES, headers=tenant.read)
    assert [m["id"] for m in listed.json()["items"]] == [out["id"]]


async def test_matrix_missing_index_409(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    s = await setup(api, tenant, database_url)
    a = s.cfg(label="have")
    c = s.cfg(label="need", chunking={"strategy": "fixed", "size": 300, "overlap": 0})
    await add_index(s, a, 1)
    r = await api.post(MATRICES, json=s.body([a, c]), headers=tenant.admin)
    assert r.status_code == 409, r.text
    err = r.json()["error"]
    assert err["code"] == "rag_index_missing"
    (missing,) = err["details"]["missing"]
    assert missing["label"] == "need"
    assert (
        missing["chunking"]["strategy"] == "fixed" and missing["embedding"]["provider"] == "local"
    )
    # nothing was created, not even the baselines that precede the failing entry
    runs = await api.get(f"{API}/runs", params={"agent_id": s.agent_id}, headers=tenant.read)
    assert runs.json()["items"] == []
    assert (await api.get(MATRICES, headers=tenant.read)).json()["items"] == []


async def test_full_context_over_limit_na(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    s = await setup(api, tenant, database_url, chars=5000)
    a = s.cfg(label="a", context_char_limit=1000)
    await add_index(s, a, 1)
    r = await api.post(MATRICES, json=s.body([a]), headers=tenant.admin)
    assert r.status_code == 201, r.text
    by = {e["kind"]: e for e in r.json()["entries"]}
    assert by["full_context"]["run_id"] is None
    assert by["full_context"]["status_note"] == "n/a: KB is 5000 chars, limit 1000"
    assert by["no_rag"]["run_id"] and by["rag"]["run_id"]
    rep = await api.get(f"{MATRICES}/{r.json()['id']}/report", headers=tenant.read)
    assert rep.status_code == 200, rep.text
    na = next(x for x in rep.json()["rows"] if x["kind"] == "full_context")
    assert na["status_note"].startswith("n/a") and na["n_calls"] == 0
    assert na["cost_per_conversation_inr"] is None


async def _seed_calls(
    s: Setup,
    run_id: str,
    calls: list[dict[str, Any]],
) -> None:
    async with await psycopg.AsyncConnection.connect(libpq_url(s.url), autocommit=True) as conn:
        for i, c in enumerate(calls):
            cur = await conn.execute(
                "INSERT INTO run_items (run_id, scenario_id, persona_id, noise_profile_id, seed) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (run_id, s.scenario_id, s.persona_id, s.noise_id, i),
            )
            item = (await cur.fetchone() or [None])[0]
            events = [
                {
                    "t_ms": 1,
                    "type": "agent_llm_usage",
                    "data": {
                        "input_tokens": c["in"],
                        "output_tokens": c["out"],
                        "latency_ms": 5,
                        "model": "m",
                    },
                }
            ]
            cur = await conn.execute(
                "INSERT INTO calls (project_id, agent_id, run_item_id, source, language, status, "
                "event_log) VALUES (%s, %s, %s, 'simulation', 'en-IN', 'completed', %s) "
                "RETURNING id",
                (s.project_id, s.agent_id, item, Jsonb(events)),
            )
            call_id = (await cur.fetchone() or [None])[0]
            await conn.execute(
                "INSERT INTO turns (call_id, idx, speaker, start_ms, end_ms) "
                "VALUES (%s, 1, 'agent', 1000, %s)",
                (call_id, 1000 + c["turn_ms"]),
            )
            if "ret" in c:
                await conn.execute(
                    "INSERT INTO retrievals (call_id, turn_idx, rag_config, query, timings, usage) "
                    "VALUES (%s, 1, '{}', 'q', %s, %s)",
                    (
                        call_id,
                        Jsonb({"total_ms": c["ret"], "embed_ms": 4}),
                        Jsonb({"embed_tokens": 10}),
                    ),
                )
            if "metrics" in c:
                await conn.execute(
                    "INSERT INTO rag_metrics (call_id, metrics, skipped) VALUES (%s, %s, %s)",
                    (call_id, Jsonb(c["metrics"]), Jsonb(c.get("skipped", []))),
                )


async def test_report_end_to_end_small(api: AsyncClient, tenant: Tenant, database_url: str) -> None:
    s = await setup(api, tenant, database_url)
    a = s.cfg(label="bm25")
    await add_index(s, a, 1, input_tokens=2000)
    m = (await api.post(MATRICES, json=s.body([a]), headers=tenant.admin)).json()
    run = {e["kind"]: e["run_id"] for e in m["entries"]}
    hit = {"hit_at_k": True, "reciprocal_rank": 1.0, "context_precision": 0.5}
    await _seed_calls(
        s,
        run["rag"],
        [
            {
                "in": 1000,
                "out": 100,
                "turn_ms": 200,
                "ret": 20,
                "metrics": {**hit, "faithfulness": 1.0, "hallucinated": False},
            },
            {
                "in": 1000,
                "out": 100,
                "turn_ms": 400,
                "ret": 40,
                "metrics": {"hit_at_k": False, "reciprocal_rank": 0.0, "hallucinated": True},
                "skipped": [{"metric": "faithfulness", "reason": "no_evidence"}],
            },
        ],
    )
    await _seed_calls(s, run["full_context"], [{"in": 10_000, "out": 100, "turn_ms": 900}])
    await _seed_calls(
        s,
        run["no_rag"],
        [{"in": 100, "out": 50, "turn_ms": 100, "metrics": {"hallucinated": True}}],
    )

    url = f"{MATRICES}/{m['id']}/report"
    rep = (await api.get(url, params={"monthly_conversations": 1000}, headers=tenant.read)).json()
    assert rep["monthly_conversations"] == 1000
    rows = {r["kind"]: r for r in rep["rows"]}
    rag = rows["rag"]
    assert rag["n_calls"] == 2 and rag["n_questions_with_truth"] == 2
    assert rag["retrieval"]["hit_rate"] == 0.5 and len(rag["retrieval"]["hit_rate_ci"]) == 2
    assert rag["generation"]["hallucination_rate"] == 0.5
    assert rag["generation"]["skipped"] == {"no_evidence": 1}
    assert rag["latency_ms"]["retrieval_p50"] == 30 and rag["latency_ms"]["turn_p50"] == 300
    assert rag["tokens_per_conversation"] == {
        "agent_input": 1000,
        "agent_output": 100,
        "query_embedding": 10,
        "rerank": 0,
    }
    assert rag["index_one_time"] == {"input_tokens": 2000, "cost_inr": 0.0}  # local embedding
    assert rag["cost_per_conversation_inr"] is None  # the agent model has no price yet
    assert rag["token_savings_vs_full_context_pct"] == 89.0
    assert rows["no_rag"]["generation"]["hallucination_rate"] == 1.0
    assert rep["recommendation"] == {
        "label": None,
        "reason": "not enough ground-truth questions (2 < 10)",
    }

    # pricing: the agent model shows up as unpriced; pricing it makes costs and savings appear
    pr = (await api.get(f"{API}/pricing", headers=tenant.read)).json()
    assert {"kind": "llm", "provider": "openai", "model": "m"} in pr["unpriced"]
    put = await api.put(
        f"{API}/pricing",
        json=[
            {
                "kind": "llm",
                "provider": "openai",
                "model": "m",
                "input_per_m_inr": 100,
                "output_per_m_inr": 400,
            }
        ],
        headers=tenant.admin,
    )
    assert put.status_code == 200, put.text
    assert put.json()["unpriced"] == [] and put.json()["prices"][0]["input_per_m_inr"] == 100
    rep = (await api.get(url, params={"monthly_conversations": 1000}, headers=tenant.read)).json()
    rows = {r["kind"]: r for r in rep["rows"]}
    assert rows["rag"]["cost_per_conversation_inr"] == 0.14
    assert rows["full_context"]["cost_per_conversation_inr"] == 1.04
    assert rows["rag"]["monthly_cost_inr"] == 140.0
    assert rows["rag"]["savings_vs_full_context"] == {"inr": 900.0, "pct": 86.5}
    assert rows["rag"]["savings_vs_no_rag"] is not None


async def test_pricing_rejects_local_price(api: AsyncClient, tenant: Tenant) -> None:
    r = await api.put(
        f"{API}/pricing",
        json=[{"kind": "embedding", "provider": "local", "model": "x", "input_per_m_inr": 1}],
        headers=tenant.admin,
    )
    assert r.status_code == 400, r.text


async def test_cross_tenant_404(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, database_url: str
) -> None:
    s = await setup(api, tenant, database_url)
    a = s.cfg()
    await add_index(s, a, 1)
    m = (await api.post(MATRICES, json=s.body([a]), headers=tenant.admin)).json()
    for path in (f"{MATRICES}/{m['id']}", f"{MATRICES}/{m['id']}/report"):
        assert (await api.get(path, headers=other_tenant.read)).status_code == 404
    assert (await api.get(MATRICES, headers=other_tenant.read)).json()["items"] == []
    # the other tenant cannot build a matrix on our agent / KB either
    r = await api.post(MATRICES, json=s.body([a]), headers=other_tenant.admin)
    assert r.status_code == 404
    pr = await api.get(f"{API}/pricing", headers=other_tenant.read)
    assert pr.json() == {"prices": [], "unpriced": []}
