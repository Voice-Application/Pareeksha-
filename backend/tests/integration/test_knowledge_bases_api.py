"""Knowledge bases API against the real app and Postgres (RAG lab Task 2)."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest
from httpx import AsyncClient

from pareeksha.api.routers import knowledge_bases
from pareeksha.audit.ingest import MAX_UPLOAD_BYTES
from pareeksha.storage.blob import LocalBlobStore
from tests.conftest import Tenant

KB = "/api/v1/knowledge-bases"

# Uploads write blobs: always use the temp-dir store, never the repo's ./data/runtime.
pytestmark = pytest.mark.usefixtures("blobs")


async def _kb(api: AsyncClient, tenant: Tenant, **body: Any) -> dict[str, Any]:
    body.setdefault("name", f"kb-{uuid.uuid4().hex[:8]}")
    r = await api.post(KB, json=body, headers=tenant.admin)
    assert r.status_code == 201, r.text
    out: dict[str, Any] = r.json()
    return out


def _upload(api: AsyncClient, tenant: Tenant, kb_id: str, name: str, data: bytes) -> Any:
    return api.post(f"{KB}/{kb_id}/documents", files={"file": (name, data)}, headers=tenant.admin)


async def test_create_kb_secrets_never_returned(
    api: AsyncClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("SECRET_KEY", Fernet.generate_key().decode())
    created = await _kb(api, tenant, secrets={"embedding_api_key": "sk-very-secret"})
    assert created["has_secrets"] is True and "sk-very-secret" not in str(created)
    got = await api.get(f"{KB}/{created['id']}", headers=tenant.read)
    assert got.json()["has_secrets"] is True and "sk-very-secret" not in got.text
    listed = await api.get(KB, headers=tenant.read)
    assert "sk-very-secret" not in listed.text
    bad = await api.post(
        KB, json={"name": "x", "secrets": {"bogus": "sk-leak-me"}}, headers=tenant.admin
    )
    assert bad.status_code == 400 and "sk-leak-me" not in bad.text
    cleared = await api.patch(f"{KB}/{created['id']}", json={"secrets": {}}, headers=tenant.admin)
    assert cleared.json()["has_secrets"] is False
    patched = await api.patch(
        f"{KB}/{created['id']}", json={"local_only": True, "description": "d"}, headers=tenant.admin
    )
    assert patched.json()["local_only"] is True and patched.json()["description"] == "d"


async def test_upload_and_dedupe(api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore) -> None:
    kb = await _kb(api, tenant)
    first = await _upload(api, tenant, kb["id"], "policy.txt", b"Refunds in 7 days")
    assert first.status_code == 201, first.text
    doc = first.json()
    assert doc["char_count"] == 17 and doc["mime"] == "text/plain" and "text" not in doc
    assert await blobs.get(f"kb/{kb['id']}/{doc['sha256']}") == b"Refunds in 7 days"
    again = await _upload(api, tenant, kb["id"], "copy.txt", b"Refunds in 7 days")
    assert again.status_code == 200 and again.json()["id"] == doc["id"]
    listed = (await api.get(f"{KB}/{kb['id']}/documents", headers=tenant.read)).json()
    assert [d["id"] for d in listed["items"]] == [doc["id"]]
    detail = (await api.get(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=tenant.read)).json()
    assert detail["text"] == "Refunds in 7 days"
    unsupported = await _upload(api, tenant, kb["id"], "a.exe", b"MZ")
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "unsupported_document"
    broken = await _upload(api, tenant, kb["id"], "a.pdf", b"nope")
    assert broken.json()["error"]["code"] == "extraction_failed"


async def test_upload_too_large_413(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore
) -> None:
    kb = await _kb(api, tenant)
    r = await _upload(api, tenant, kb["id"], "big.txt", b"a" * (MAX_UPLOAD_BYTES + 1))
    assert r.status_code == 413 and r.json()["error"]["code"] == "file_too_large"


async def test_cross_tenant_404(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant, blobs: LocalBlobStore
) -> None:
    kb = await _kb(api, tenant)
    doc = (await _upload(api, tenant, kb["id"], "a.txt", b"hello")).json()
    mine = await _kb(api, other_tenant)
    for r in (
        await api.get(f"{KB}/{kb['id']}", headers=other_tenant.read),
        await api.patch(f"{KB}/{kb['id']}", json={"name": "z"}, headers=other_tenant.admin),
        await _upload(api, other_tenant, kb["id"], "b.txt", b"x"),
        await api.get(f"{KB}/{kb['id']}/documents", headers=other_tenant.read),
        await api.get(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=other_tenant.read),
        await api.get(f"{KB}/{mine['id']}/documents/{doc['id']}", headers=other_tenant.read),
        await api.delete(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=other_tenant.admin),
    ):
        assert r.status_code == 404, r.text
    ids = [k["id"] for k in (await api.get(KB, headers=other_tenant.read)).json()["items"]]
    assert kb["id"] not in ids


async def test_kb_char_limit_409(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge_bases, "MAX_CHARS", 10)
    kb = await _kb(api, tenant)
    assert (await _upload(api, tenant, kb["id"], "a.txt", b"123456")).status_code == 201
    r = await _upload(api, tenant, kb["id"], "b.txt", b"abcdef")
    assert r.status_code == 409 and r.json()["error"]["code"] == "kb_limit_reached"


async def test_kb_document_count_limit_409(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge_bases, "MAX_DOCUMENTS", 1)
    kb = await _kb(api, tenant)
    assert (await _upload(api, tenant, kb["id"], "a.txt", b"one")).status_code == 201
    r = await _upload(api, tenant, kb["id"], "b.txt", b"two")
    assert r.status_code == 409 and r.json()["error"]["code"] == "kb_limit_reached"


async def test_extraction_timeout_422(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    def slow(name: str, data: bytes) -> tuple[str, str]:
        time.sleep(0.5)
        return "text/plain", "x"

    monkeypatch.setattr(knowledge_bases, "EXTRACT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(knowledge_bases, "extract_text", slow)
    kb = await _kb(api, tenant)
    r = await _upload(api, tenant, kb["id"], "a.txt", b"hi")
    assert r.status_code == 422 and r.json()["error"]["code"] == "extraction_failed"


async def test_delete_document(api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore) -> None:
    kb = await _kb(api, tenant)
    doc = (await _upload(api, tenant, kb["id"], "a.txt", b"hello")).json()
    r = await api.delete(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=tenant.admin)
    assert r.status_code == 204
    gone = await api.get(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=tenant.read)
    assert gone.status_code == 404
    listed = (await api.get(f"{KB}/{kb['id']}/documents", headers=tenant.read)).json()
    assert listed["items"] == []
    again = await api.delete(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=tenant.admin)
    assert again.status_code == 204  # idempotent


async def test_deleted_documents_do_not_count_toward_limits(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(knowledge_bases, "MAX_DOCUMENTS", 1)
    kb = await _kb(api, tenant)
    doc = (await _upload(api, tenant, kb["id"], "a.txt", b"one")).json()
    await api.delete(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=tenant.admin)
    assert (await _upload(api, tenant, kb["id"], "b.txt", b"two")).status_code == 201


async def test_reupload_restores_deleted_document(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore
) -> None:
    kb = await _kb(api, tenant)
    doc = (await _upload(api, tenant, kb["id"], "a.txt", b"hello")).json()
    await api.delete(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=tenant.admin)
    again = await _upload(api, tenant, kb["id"], "renamed.txt", b"hello")
    assert again.status_code == 201 and again.json()["id"] == doc["id"]
    assert again.json()["filename"] == "renamed.txt"
    got = await api.get(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=tenant.read)
    assert got.status_code == 200 and got.json()["text"] == "hello"
    dup = await _upload(api, tenant, kb["id"], "renamed.txt", b"hello")
    assert dup.status_code == 200


async def test_deleted_document_kept_for_existing_index_chunks(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, pg: Any
) -> None:
    kb = await _kb(api, tenant)
    doc = (await _upload(api, tenant, kb["id"], "a.txt", b"hello world")).json()
    index_id = uuid.uuid4()
    await pg.execute(
        "INSERT INTO kb_indexes (id, kb_id, project_id, version, index_key, chunking, embedding)"
        " VALUES (%s, %s, %s, 1, 'k', '{}', '{}')",
        (index_id, kb["id"], tenant.project_id),
    )
    await pg.execute(
        "INSERT INTO kb_chunks (index_id, document_id, ordinal, text, start_char, end_char,"
        " parent_start, parent_end, text_sha) VALUES (%s, %s, 0, 'hello', 0, 5, 0, 5, 'x')",
        (index_id, doc["id"]),
    )
    r = await api.delete(f"{KB}/{kb['id']}/documents/{doc['id']}", headers=tenant.admin)
    assert r.status_code == 204
    cur = await pg.execute("SELECT count(*) FROM kb_chunks WHERE index_id = %s", (index_id,))
    assert (await cur.fetchone())[0] == 1
    # a hard delete of the document row is refused while chunks reference it
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        await pg.execute("DELETE FROM kb_documents WHERE id = %s", (doc["id"],))


async def test_kb_delete_cascades_documents_indexes_and_chunks(
    api: AsyncClient, tenant: Tenant, blobs: LocalBlobStore, pg: Any
) -> None:
    kb = await _kb(api, tenant)
    doc = (await _upload(api, tenant, kb["id"], "a.txt", b"hello world")).json()
    index_id = uuid.uuid4()
    await pg.execute(
        "INSERT INTO kb_indexes (id, kb_id, project_id, version, index_key, chunking, embedding)"
        " VALUES (%s, %s, %s, 1, 'k', '{}', '{}')",
        (index_id, kb["id"], tenant.project_id),
    )
    await pg.execute(
        "INSERT INTO kb_chunks (index_id, document_id, ordinal, text, start_char, end_char,"
        " parent_start, parent_end, text_sha) VALUES (%s, %s, 0, 'hello', 0, 5, 0, 5, 'x')",
        (index_id, doc["id"]),
    )
    await pg.execute("DELETE FROM knowledge_bases WHERE id = %s", (kb["id"],))
    for table, col in (("kb_chunks", "index_id"), ("kb_indexes", "id"), ("kb_documents", "kb_id")):
        cur = await pg.execute(
            f"SELECT count(*) FROM {table} WHERE {col} = %s",
            (index_id if col == "index_id" or table == "kb_indexes" else kb["id"],),
        )
        assert (await cur.fetchone())[0] == 0, table
