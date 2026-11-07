"""Index builds end to end: POST -> outbox -> the ``indexer`` handler (fake embedder) -> chunks."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.agent_llm.base import AgentLLMError
from pareeksha.events.consumer import Ctx
from pareeksha.events.schemas import KbIndexRequested
from pareeksha.events.topics import MAX_ATTEMPTS
from pareeksha.rag.embeddings import EmbedResult
from pareeksha.workers.indexer import handle_index_requested
from tests.conftest import Tenant
from tests.integration.domain import outbox_for

KB = "/api/v1/knowledge-bases"
SMALL = {"strategy": "fixed", "size": 100, "overlap": 0}
TEXT = " ".join(f"Sentence number {i} about refunds and delivery." for i in range(40)).encode()


class FakeEmbedder:
    def __init__(self, error: Exception | None = None) -> None:
        self.texts: list[str] = []
        self.error = error

    async def embed(self, texts: Any, *, kind: str) -> EmbedResult:
        if self.error:
            raise self.error
        self.texts.extend(texts)
        return EmbedResult(
            [[float(len(t)), 1.0] for t in texts], input_tokens=len(texts), latency_ms=3
        )


async def _kb(api: AsyncClient, tenant: Tenant, **body: Any) -> str:
    body.setdefault("name", f"kb-{uuid.uuid4().hex[:8]}")
    r = await api.post(KB, json=body, headers=tenant.admin)
    assert r.status_code == 201, r.text
    kb_id: str = r.json()["id"]
    up = await api.post(
        f"{KB}/{kb_id}/documents", files={"file": ("a.txt", TEXT)}, headers=tenant.admin
    )
    assert up.status_code == 201, up.text
    return kb_id


async def _request(
    api: AsyncClient, tenant: Tenant, kb_id: str, chunking: dict[str, Any] = SMALL
) -> Any:
    return await api.post(
        f"{KB}/{kb_id}/indexes",
        json={"chunking": chunking, "embedding": {}},
        headers=tenant.admin,
    )


async def _run(
    factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
    index_id: str,
    embedder: FakeEmbedder,
    attempt: int = 1,
) -> None:
    (env,) = await outbox_for(factory, "index_id", index_id)
    assert isinstance(env.payload, KbIndexRequested)
    ctx = Ctx(tx=pg, group="indexer", topic=env.topic.value, partition=0, offset=0, attempt=attempt)
    async with pg.transaction():
        await handle_index_requested(
            env,  # type: ignore[arg-type]
            ctx,
            lambda _cfg, _key: embedder,
        )


async def _get(api: AsyncClient, tenant: Tenant, kb_id: str, index_id: str) -> dict[str, Any]:
    r = await api.get(f"{KB}/{kb_id}/indexes/{index_id}", headers=tenant.read)
    out: dict[str, Any] = r.json()
    return out


async def test_build_creates_chunks_and_vectors(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    kb_id = await _kb(api, tenant)
    accepted = await _request(api, tenant, kb_id)
    assert accepted.status_code == 202, accepted.text
    idx = accepted.json()
    assert (idx["status"], idx["version"], idx["chunk_count"]) == ("pending", 1, 0)

    fake = FakeEmbedder()
    await _run(session_factory, pg, idx["id"], fake)
    await _run(session_factory, pg, idx["id"], fake)  # redelivery: no second build
    done = await _get(api, tenant, kb_id, idx["id"])
    assert done["status"] == "ready" and done["error"] is None and done["finished_at"]
    assert done["chunk_count"] > 1
    stats = done["stats"]
    assert stats["documents"] == 1 and stats["chunks"] == done["chunk_count"]
    assert stats["embedded"] + stats["reused"] == stats["chunks"]
    assert stats["input_tokens"] == len(fake.texts)

    chunks = await api.get(f"{KB}/{kb_id}/indexes/{idx['id']}/chunks?limit=5", headers=tenant.read)
    body = chunks.json()
    assert [c["ordinal"] for c in body] == [0, 1, 2, 3, 4] and "embedding" not in body[0]
    cur = await pg.execute(
        "SELECT count(*), count(embedding) FROM kb_chunks WHERE index_id = %s", (idx["id"],)
    )
    assert await cur.fetchone() == (done["chunk_count"], done["chunk_count"])
    listed = await api.get(f"{KB}/{kb_id}/indexes", headers=tenant.read)
    assert [i["id"] for i in listed.json()["items"]] == [idx["id"]]


async def test_second_build_reuses_embeddings(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    kb_id = await _kb(api, tenant)
    first = (await _request(api, tenant, kb_id)).json()
    await _run(session_factory, pg, first["id"], FakeEmbedder())
    # a different chunking of the same text builds a new index; identical chunks are reused
    second = await _request(api, tenant, kb_id, {**SMALL, "overlap": 1})
    assert second.status_code == 202 and second.json()["version"] == 2
    # same chunk texts again, forced through a new row (chunking differs only in unused window)
    third = (await _request(api, tenant, kb_id, {**SMALL, "window": 3})).json()
    fake = FakeEmbedder()
    await _run(session_factory, pg, third["id"], fake)
    done = await _get(api, tenant, kb_id, third["id"])
    assert done["status"] == "ready"
    assert done["stats"]["embedded"] == 0 and done["stats"]["reused"] == done["chunk_count"]
    assert fake.texts == []


async def test_rebuild_same_key_returns_existing(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    kb_id = await _kb(api, tenant)
    first = (await _request(api, tenant, kb_id)).json()
    await _run(session_factory, pg, first["id"], FakeEmbedder())
    again = await _request(api, tenant, kb_id)
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    # a new document changes the snapshot, so it is a new build
    up = await api.post(
        f"{KB}/{kb_id}/documents", files={"file": ("b.txt", b"other text")}, headers=tenant.admin
    )
    assert up.status_code == 201
    newer = await _request(api, tenant, kb_id)
    assert newer.status_code == 202 and newer.json()["version"] == 2


async def test_local_only_kb_with_hosted_embedding_fails(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    kb_id = await _kb(api, tenant)
    body = {
        "chunking": SMALL,
        "embedding": {"provider": "openai", "model": "text-embedding-3-small"},
    }
    ok = await api.post(f"{KB}/{kb_id}/indexes", json=body, headers=tenant.admin)
    assert ok.status_code == 202, ok.text
    await api.patch(f"{KB}/{kb_id}", json={"local_only": True}, headers=tenant.admin)
    refused = await api.post(f"{KB}/{kb_id}/indexes", json=body, headers=tenant.admin)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "local_only"

    fake = FakeEmbedder()
    await _run(session_factory, pg, ok.json()["id"], fake)  # flipped after the request
    done = await _get(api, tenant, kb_id, ok.json()["id"])
    assert done["status"] == "failed" and "local" in done["error"] and fake.texts == []


async def test_provider_errors_retry_then_fail_without_the_key(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    kb_id = await _kb(api, tenant)
    idx = (await _request(api, tenant, kb_id)).json()
    boom = FakeEmbedder(AgentLLMError("provider returned HTTP 503", status=503, retryable=True))
    with pytest.raises(AgentLLMError):
        await _run(session_factory, pg, idx["id"], boom, attempt=1)
    assert (await _get(api, tenant, kb_id, idx["id"]))["status"] == "pending"
    await _run(session_factory, pg, idx["id"], boom, attempt=MAX_ATTEMPTS)
    done = await _get(api, tenant, kb_id, idx["id"])
    assert done["status"] == "failed" and "503" in done["error"]
