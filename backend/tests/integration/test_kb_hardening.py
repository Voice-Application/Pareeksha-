"""Knowledge-base upload hardening: bounded extraction threads, upload race, body cap, models."""

from __future__ import annotations

import asyncio
import threading
import uuid
import weakref
from typing import Any

import pytest
from httpx import AsyncClient

from pareeksha.api.routers import knowledge_bases as kb_router
from pareeksha.audit.ingest import MAX_UPLOAD_BYTES
from pareeksha.rag import local_models
from tests.conftest import Tenant
from tests.integration.runs_support import API
from tests.integration.test_rag_runs import env, setup  # noqa: F401  (autouse env fixture)

KB = f"{API}/knowledge-bases"
pytestmark = pytest.mark.usefixtures("blobs")


async def make_kb(api: AsyncClient, tenant: Tenant, **body: Any) -> str:
    r = await api.post(
        KB, json={"name": f"kb-{uuid.uuid4().hex[:8]}", **body}, headers=tenant.admin
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def upload(api: AsyncClient, tenant: Tenant, kb_id: str, body: bytes) -> Any:
    return await api.post(
        f"{KB}/{kb_id}/documents",
        files={"file": (f"{uuid.uuid4().hex[:6]}.txt", body)},
        headers=tenant.admin,
    )


async def test_hostile_uploads_cannot_pile_up_threads(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, started = threading.Event(), []

    def hang(filename: str, data: bytes) -> tuple[str, str]:
        started.append(filename)
        release.wait(10)  # a thread cannot be killed: it runs until released
        return "text/plain", data.decode()

    monkeypatch.setattr(kb_router, "extract_text", hang)
    monkeypatch.setattr(kb_router, "_THREAD_SLOTS", weakref.WeakKeyDictionary())
    monkeypatch.setattr(kb_router, "EXTRACT_TIMEOUT_S", 0.5)
    kb_id = await make_kb(api, tenant)
    try:
        results = await asyncio.gather(
            *[upload(api, tenant, kb_id, f"doc {i}".encode()) for i in range(5)]
        )
        assert [r.status_code for r in results] == [422] * 5
        assert {r.json()["error"]["code"] for r in results} == {"extraction_failed"}
        assert len(started) == 2  # the other three never got a thread
    finally:
        release.set()
    await asyncio.sleep(0.3)  # the finished threads give their slots back
    ok = await upload(api, tenant, kb_id, b"fine")
    assert ok.status_code == 201, ok.text


async def test_concurrent_uploads_cannot_exceed_the_document_limit(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kb_router, "MAX_DOCUMENTS", 1)
    kb_id = await make_kb(api, tenant)
    results = await asyncio.gather(
        *[upload(api, tenant, kb_id, f"document number {i}".encode()) for i in range(4)]
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409], [r.text for r in results]
    listed = await api.get(f"{KB}/{kb_id}/documents", headers=tenant.read)
    assert len(listed.json()["items"]) == 1


async def test_concurrent_uploads_cannot_exceed_the_character_limit(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(kb_router, "MAX_CHARS", 30)
    kb_id = await make_kb(api, tenant)
    results = await asyncio.gather(
        *[upload(api, tenant, kb_id, (f"{i}" * 20).encode()) for i in range(3)]
    )
    assert sorted(r.status_code for r in results) == [201, 409, 409]


async def test_oversized_body_is_refused_before_it_is_parsed(
    api: AsyncClient, tenant: Tenant
) -> None:
    kb_id = await make_kb(api, tenant)
    big = b"x" * (MAX_UPLOAD_BYTES + kb_router.MULTIPART_SLACK + 1)
    r = await upload(api, tenant, kb_id, big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"
    assert r.json()["error"]["details"] == {"max_bytes": MAX_UPLOAD_BYTES}
    csv = await api.post(
        f"{KB}/{kb_id}/questions:import",
        data={"agent_id": str(uuid.uuid4())},
        files={"file": ("q.csv", big)},
        headers=tenant.admin,
    )
    assert csv.status_code == 413 and csv.json()["error"]["code"] == "file_too_large"
    # a file just over the limit still gets the endpoint's own answer
    over = await upload(api, tenant, kb_id, b"x" * (MAX_UPLOAD_BYTES + 1))
    assert (
        over.status_code == 413 and over.json()["error"]["message"] == "File is larger than 10 MB"
    )


async def test_unsupported_local_model_is_refused_at_index_build(
    api: AsyncClient, tenant: Tenant
) -> None:
    kb_id = await make_kb(api, tenant)
    assert (await upload(api, tenant, kb_id, b"some text")).status_code == 201
    r = await api.post(
        f"{KB}/{kb_id}/indexes",
        json={"embedding": {"provider": "local", "model": "evil/not-a-listed-model"}},
        headers=tenant.admin,
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_model", r.text
    listed = await api.get(f"{KB}/{kb_id}/indexes", headers=tenant.read)
    assert listed.json()["items"] == []
    # hosted providers name models fastembed knows nothing about: not checked
    ok = await api.post(
        f"{KB}/{kb_id}/indexes",
        json={"embedding": {"provider": "openai", "model": "text-embedding-3-small"}},
        headers=tenant.admin,
    )
    assert ok.status_code == 202, ok.text


async def test_the_fastembed_list_is_the_authority(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        local_models, "supported_embedding_models", lambda: frozenset({"only/this"})
    )
    kb_id = await make_kb(api, tenant)
    assert (await upload(api, tenant, kb_id, b"some text")).status_code == 201
    default = await api.post(f"{KB}/{kb_id}/indexes", json={}, headers=tenant.admin)
    assert default.status_code == 422 and default.json()["error"]["code"] == "unsupported_model"
    ok = await api.post(
        f"{KB}/{kb_id}/indexes",
        json={"embedding": {"provider": "local", "model": "only/this"}},
        headers=tenant.admin,
    )
    assert ok.status_code == 202, ok.text


async def test_unsupported_local_model_is_refused_at_run_creation(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, database_url: str
) -> None:
    bad = {"embedding": {"provider": "local", "model": "evil/not-a-listed-model"}}
    s = await setup(api, tenant, database_url, rag={"method": "dense", **bad})
    r = await api.post(f"{API}/runs", json=s.body, headers=tenant.admin)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_model", r.text
    rerank = await setup(
        api,
        other_tenant,  # agent names are unique per project
        database_url,
        rag={"method": "hybrid_rerank", "reranker_model": "evil/reranker"},
    )
    r = await api.post(f"{API}/runs", json=rerank.body, headers=other_tenant.admin)
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_model", r.text
