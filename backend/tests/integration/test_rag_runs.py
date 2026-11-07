"""RAG in runs: the index is pinned at run creation, guards answer 409, retrievals are saved."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from cryptography.fernet import Fernet
from httpx import AsyncClient

from pareeksha.events.runtime import Database
from pareeksha.events.schemas import CallCompleted, CallRequested, make_envelope
from pareeksha.events.settings import libpq_url
from pareeksha.llm.usage_db import ApiUsageSink
from pareeksha.schemas.rag import RagConfig, index_key
from pareeksha.storage.blob import LocalBlobStore
from pareeksha.workers import simulator
from tests.conftest import Tenant
from tests.integration.audit_support import fetch_rows, transaction
from tests.integration.runs_support import API, make_fixture, plan_in_db, settings_for
from tests.unit.simulation.simfakes import ScriptedCaller
from tests.unit.simulation.test_text_runner import FakeChat, text

KB = f"{API}/knowledge-bases"
EXTRA = {"sha256": "x", "blob_key": "k", "mime": "text/plain"}


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
    await db.close()
    await usage.close()


class Setup:
    def __init__(self, body: dict[str, Any], kb_id: str, project_id: Any, cfg: RagConfig) -> None:
        self.body, self.kb_id, self.project_id, self.cfg = body, kb_id, project_id, cfg


async def setup(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    *,
    provider: str = "openai",
    local_only: bool = False,
    rag: dict[str, Any] | None = None,
    run_rag: dict[str, Any] | None = None,
) -> Setup:
    fx = await make_fixture(api, tenant, 0, 1, 1)
    kb = await api.post(
        KB,
        json={"name": f"kb-{uuid.uuid4().hex[:8]}", "local_only": local_only},
        headers=tenant.admin,
    )
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]
    cfg = RagConfig.model_validate({"kb_id": kb_id, "method": "bm25", "top_k": 1, **(rag or {})})
    agent = await api.post(
        f"{API}/agents",
        json={"name": "rag-bot", "adapter": "prompt", "adapter_secrets": {"api_key": "sk-x"}},
        headers=tenant.admin,
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]
    version = await api.post(
        f"{API}/agents/{agent_id}/prompt-versions",
        json={
            "system_prompt": "Answer using:\n{{context}}",
            "provider": provider,
            "model": "m",
            "rag_config": cfg.model_dump(mode="json"),
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
    body: dict[str, Any] = {
        "agent_id": agent_id,
        "name": "rag run",
        "scenario_ids": [scenario.json()["id"]],
        "persona_ids": fx.persona_ids,
        "noise_profile_ids": fx.noise_profile_ids,
    }
    if run_rag is not None:
        body["config"] = {"rag": {"kb_id": kb_id, **run_rag}}
    async with await psycopg.AsyncConnection.connect(
        libpq_url(database_url), autocommit=True
    ) as conn:
        cur = await conn.execute("SELECT project_id FROM agents WHERE id = %s", (agent_id,))
        row = await cur.fetchone()
        assert row is not None
    return Setup(body, kb_id, row[0], cfg)


async def add_index(
    database_url: str, s: Setup, chunk_text: str, *, version: int, status: str = "ready"
) -> uuid.UUID:
    index_id, doc_id = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(
        libpq_url(database_url), autocommit=True
    ) as conn:
        await conn.execute(
            "INSERT INTO kb_documents (id, kb_id, project_id, filename, mime, sha256, text, "
            "char_count, blob_key) VALUES (%s, %s, %s, 'faq.txt', 'text/plain', %s, %s, %s, 'k')",
            (doc_id, s.kb_id, s.project_id, uuid.uuid4().hex, chunk_text, len(chunk_text)),
        )
        await conn.execute(
            "INSERT INTO kb_indexes (id, kb_id, project_id, version, index_key, chunking, "
            "embedding, status, document_ids, chunk_count) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)",
            (
                index_id,
                s.kb_id,
                s.project_id,
                version,
                index_key(s.cfg),
                json.dumps(s.cfg.chunking.model_dump(mode="json")),
                json.dumps(s.cfg.embedding.model_dump(mode="json")),
                status,
                json.dumps([str(doc_id)]),
            ),
        )
        await conn.execute(
            "INSERT INTO kb_chunks (index_id, document_id, ordinal, text, start_char, end_char, "
            "parent_start, parent_end, text_sha, embedding) "
            "VALUES (%s, %s, 0, %s, 0, %s, 0, %s, %s, %s)",
            (
                index_id,
                doc_id,
                chunk_text,
                len(chunk_text),
                len(chunk_text),
                uuid.uuid4().hex,
                [0.1, 0.2, 0.3],
            ),
        )
    return index_id


async def test_run_pins_ready_index(api: AsyncClient, tenant: Tenant, database_url: str) -> None:
    s = await setup(api, tenant, database_url)
    await add_index(database_url, s, "old refunds text", version=1)
    newest = await add_index(database_url, s, "new refunds text", version=2)
    await add_index(database_url, s, "broken", version=3, status="failed")
    created = await api.post(f"{API}/runs", json=s.body, headers=tenant.admin)
    assert created.status_code == 201, created.text
    rows = await fetch_rows(
        database_url, "SELECT config FROM test_runs WHERE id = %s", created.json()["id"]
    )
    assert rows[0]["config"]["rag_index_id"] == str(newest)


async def test_run_without_index_409(api: AsyncClient, tenant: Tenant, database_url: str) -> None:
    s = await setup(api, tenant, database_url)
    await add_index(database_url, s, "x", version=1, status="building")
    r = await api.post(f"{API}/runs", json=s.body, headers=tenant.admin)
    assert r.status_code == 409, r.text
    err = r.json()["error"]
    assert err["code"] == "rag_index_missing" and err["details"]["kb_id"] == s.kb_id
    assert err["details"]["chunking"]["strategy"] == "recursive"


async def test_local_only_hosted_agent_409(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    s = await setup(api, tenant, database_url, local_only=True, provider="openai")
    await add_index(database_url, s, "x", version=1)
    r = await api.post(f"{API}/runs", json=s.body, headers=tenant.admin)
    assert r.status_code == 409 and r.json()["error"]["code"] == "local_only", r.text


async def test_full_context_too_large_409(
    api: AsyncClient, tenant: Tenant, database_url: str
) -> None:
    s = await setup(
        api, tenant, database_url, rag={"mode": "full_context", "context_char_limit": 5}
    )
    await add_index(database_url, s, "far more than five chars", version=1)
    r = await api.post(f"{API}/runs", json=s.body, headers=tenant.admin)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "full_context_too_large"
    assert r.json()["error"]["details"]["chars"] == len("far more than five chars")


async def test_save_call_writes_retrievals(
    api: AsyncClient,
    tenant: Tenant,
    database_url: str,
    workers: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = await setup(api, tenant, database_url)
    pinned = await add_index(database_url, s, "Refunds take seven days.", version=1)
    created = await api.post(f"{API}/runs", json=s.body, headers=tenant.admin)
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    # a newer ready index appearing after the run was created must not be used
    await add_index(database_url, s, "Refunds take forty days.", version=2)
    (req,) = [
        o.payload
        for o in await plan_in_db(database_url, run_id)
        if isinstance(o.payload, CallRequested)
    ]
    chat = FakeChat([text("Seven days.")])
    monkeypatch.setattr(simulator, "build_chat_provider", lambda *a, **k: chat)
    monkeypatch.setattr(simulator, "_caller", ScriptedCaller(["How long do refunds take?"]))
    env = make_envelope(req, producer="planner", correlation_id=run_id)
    async with transaction(database_url) as ctx:
        (out,) = await simulator.on_call_requested(env, ctx)
    assert isinstance(out.payload, CallCompleted)
    system = chat.seen[0][0].content
    assert "Refunds take seven days." in system and "forty" not in system

    rows = await fetch_rows(
        database_url,
        "SELECT r.* FROM retrievals r JOIN calls c ON c.id = r.call_id "
        "JOIN run_items i ON i.id = c.run_item_id WHERE i.run_id = %s",
        run_id,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["turn_idx"] == 1 and row["index_id"] == pinned
    assert row["query"] == "How long do refunds take?"
    assert row["results"][0]["text"] == "Refunds take seven days."
    assert row["context_chars"] == len(system) - len("Answer using:\n")
    assert row["rag_config"]["method"] == "bm25"
