"""API key create / list / revoke against the real app and Postgres (FR-IN-2 auth surface)."""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.auth import DISPLAY_PREFIX_LEN, KEY_PREFIX, hash_api_key
from pareeksha.db.models import ApiKeys
from tests.conftest import Tenant, bearer


async def test_create_returns_the_full_key_once_and_it_works(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    response = await api.post(
        "/api/v1/api-keys",
        json={"name": "github-actions", "scopes": ["read", "runs:write", "read"]},
        headers=tenant.admin,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    key = body["key"]
    assert key.startswith(KEY_PREFIX) and body["prefix"] == key[:DISPLAY_PREFIX_LEN]
    assert body["scopes"] == ["read", "runs:write"]  # duplicates dropped
    assert body["revoked_at"] is None and body["last_used_at"] is None

    async with session_factory() as session:
        row = await session.get(ApiKeys, uuid.UUID(body["id"]))
    assert row is not None and row.project_id == tenant.project_id
    assert row.key_hash == hash_api_key(key) and key not in {row.key_hash, row.prefix, row.name}

    assert (await api.get("/api/v1/agents", headers=bearer(key))).status_code == 200
    created_agent = await api.post(
        "/api/v1/agents",
        json={"name": "via new key", "endpoint_url": "ws://x"},
        headers=bearer(key),
    )
    assert created_agent.status_code == 201  # runs:write granted
    assert (await api.get("/api/v1/api-keys", headers=bearer(key))).status_code == 403


async def test_list_shows_prefix_scopes_and_use_but_never_the_key(
    api: AsyncClient, tenant: Tenant
) -> None:
    created = (
        await api.post(
            "/api/v1/api-keys", json={"name": "ci", "scopes": ["read"]}, headers=tenant.admin
        )
    ).json()
    await api.get("/api/v1/agents", headers=bearer(created["key"]))  # a use of the key

    listed = await api.get("/api/v1/api-keys", headers=tenant.admin)
    assert listed.status_code == 200
    assert created["key"] not in listed.text and "key_hash" not in listed.text
    items = {k["id"]: k for k in listed.json()["items"]}
    assert set(items) >= {created["id"]}
    entry = items[created["id"]]
    assert entry["name"] == "ci" and entry["scopes"] == ["read"]
    assert entry["prefix"] == created["prefix"] and entry["last_used_at"] is not None
    assert "key" not in entry


async def test_default_scope_is_read(api: AsyncClient, tenant: Tenant) -> None:
    created = await api.post("/api/v1/api-keys", json={"name": "default"}, headers=tenant.admin)
    assert created.json()["scopes"] == ["read"]


async def test_revoke_stops_the_key_and_is_idempotent(
    api: AsyncClient, tenant: Tenant, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    created = (
        await api.post("/api/v1/api-keys", json={"name": "tmp"}, headers=tenant.admin)
    ).json()
    assert (await api.get("/api/v1/agents", headers=bearer(created["key"]))).status_code == 200

    revoked = await api.delete(f"/api/v1/api-keys/{created['id']}", headers=tenant.admin)
    assert revoked.status_code == 204 and revoked.content == b""
    denied = await api.get("/api/v1/agents", headers=bearer(created["key"]))
    assert denied.status_code == 401 and denied.json()["error"]["code"] == "unauthorized"

    async with session_factory() as session:
        first = await session.scalar(
            select(ApiKeys.revoked_at).where(ApiKeys.id == uuid.UUID(created["id"]))
        )
    assert first is not None
    again = await api.delete(f"/api/v1/api-keys/{created['id']}", headers=tenant.admin)
    assert again.status_code == 204
    async with session_factory() as session:
        second = await session.scalar(
            select(ApiKeys.revoked_at).where(ApiKeys.id == uuid.UUID(created["id"]))
        )
    assert second == first  # the original revocation time is kept

    listed = (await api.get("/api/v1/api-keys", headers=tenant.admin)).json()["items"]
    assert {k["id"]: k["revoked_at"] for k in listed}[created["id"]] is not None


async def test_admin_only_and_project_isolation(
    api: AsyncClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    for method, path in (("POST", "/api-keys"), ("GET", "/api-keys")):
        denied = await api.request(
            method,
            f"/api/v1{path}",
            json={"name": "x"} if method == "POST" else None,
            headers=tenant.read,
        )
        assert denied.status_code == 403
    created = (
        await api.post("/api/v1/api-keys", json={"name": "mine"}, headers=tenant.admin)
    ).json()
    foreign = await api.delete(f"/api/v1/api-keys/{created['id']}", headers=other_tenant.admin)
    assert foreign.status_code == 404
    others = (await api.get("/api/v1/api-keys", headers=other_tenant.admin)).json()["items"]
    assert created["id"] not in {k["id"] for k in others}
    ghost = await api.delete(f"/api/v1/api-keys/{uuid.uuid4()}", headers=tenant.admin)
    assert ghost.status_code == 404 and ghost.json()["error"]["code"] == "not_found"
    bad_scope = await api.post(
        "/api/v1/api-keys", json={"name": "x", "scopes": ["root"]}, headers=tenant.admin
    )
    assert bad_scope.status_code == 400
