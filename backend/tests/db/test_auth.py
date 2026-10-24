"""API-key authentication against real Postgres: hashing, scopes, revocation, last use."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.auth import (
    DISPLAY_PREFIX_LEN,
    KEY_PREFIX,
    generate_api_key,
    has_scope,
    hash_api_key,
)
from pareeksha.api.main import app
from pareeksha.db.models import ApiKeys, Projects
from pareeksha.db.session import get_session, get_session_factory

READ_ROUTE = "/api/v1/agents"  # needs "read"; 501 once auth passes (handler is an API-02 stub)
ADMIN_ROUTE = "/api/v1/api-keys"  # needs "admin"


@pytest.fixture(autouse=True)
def _use_test_database(session_factory: async_sessionmaker[AsyncSession]) -> Iterator[None]:
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    yield
    app.dependency_overrides.pop(get_session_factory, None)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _make_key(
    factory: async_sessionmaker[AsyncSession], scopes: list[str], *, revoked: bool = False
) -> tuple[str, uuid.UUID]:
    key, prefix, key_hash = generate_api_key()
    async with factory() as session:
        project = Projects(name=f"p-{uuid.uuid4().hex[:6]}")
        session.add(project)
        await session.flush()
        row = ApiKeys(
            project_id=project.id,
            name="test",
            prefix=prefix,
            key_hash=key_hash,
            scopes=scopes,
            revoked_at=text("now()") if revoked else None,
        )
        session.add(row)
        await session.commit()
        return key, row.id


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def test_generated_key_shape_and_hash() -> None:
    key, prefix, key_hash = generate_api_key()
    assert key.startswith(KEY_PREFIX) and len(key) > 40
    assert prefix == key[:DISPLAY_PREFIX_LEN] and len(prefix) == 16
    assert key_hash == hash_api_key(key) and key not in key_hash and len(key_hash) == 64
    assert generate_api_key()[0] != key


def test_admin_implies_every_scope() -> None:
    assert has_scope(["admin"], ["runs:write"])
    assert has_scope(["read"], ["read"])
    assert not has_scope(["read"], ["runs:write"])
    assert has_scope([], [])  # no scope required: any valid key


async def test_missing_and_unknown_keys_are_401(client: AsyncClient) -> None:
    missing = await client.get(READ_ROUTE)
    assert missing.status_code == 401 and missing.json()["error"]["code"] == "unauthorized"
    unknown = await client.get(READ_ROUTE, headers=_bearer("pk_live_does-not-exist"))
    assert unknown.status_code == 401
    assert unknown.headers["www-authenticate"] == "Bearer"


async def test_valid_key_with_scope_passes_auth(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    key, _ = await _make_key(session_factory, ["read"])
    response = await client.get(READ_ROUTE, headers=_bearer(key))
    assert response.status_code == 501  # authenticated; the handler itself is a later task


async def test_insufficient_scope_is_403(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    key, key_id = await _make_key(session_factory, ["read"])
    response = await client.get(ADMIN_ROUTE, headers=_bearer(key))
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "forbidden"
    assert error["details"]["required"] == ["admin"]
    async with session_factory() as session:  # a rejected request is not a use of the key
        used = await session.scalar(select(ApiKeys.last_used_at).where(ApiKeys.id == key_id))
    assert used is None


async def test_admin_key_reaches_every_route(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    key, _ = await _make_key(session_factory, ["admin"])
    assert (await client.get(ADMIN_ROUTE, headers=_bearer(key))).status_code == 501
    assert (await client.get(READ_ROUTE, headers=_bearer(key))).status_code == 501


async def test_revoked_key_is_401(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    key, _ = await _make_key(session_factory, ["admin"], revoked=True)
    response = await client.get(READ_ROUTE, headers=_bearer(key))
    assert response.status_code == 401


async def test_last_used_at_is_updated(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    key, key_id = await _make_key(session_factory, ["read"])
    await client.get(READ_ROUTE, headers=_bearer(key))
    async with session_factory() as session:
        used = await session.scalar(select(ApiKeys.last_used_at).where(ApiKeys.id == key_id))
    assert used is not None


async def test_only_the_hash_is_stored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    key, key_id = await _make_key(session_factory, ["read"])
    async with session_factory() as session:
        row = await session.get(ApiKeys, key_id)
    assert row is not None and row.key_hash == hash_api_key(key)
    assert key not in {row.key_hash, row.prefix, row.name}


async def test_get_session_commits_on_success_and_rolls_back_on_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    gen = get_session(session_factory)
    session = await anext(gen)
    session.add(Projects(name="committed"))
    with pytest.raises(StopAsyncIteration):
        await anext(gen)

    failing = cast(AsyncGenerator[AsyncSession, None], get_session(session_factory))
    session = await anext(failing)
    session.add(Projects(name="rolled-back"))
    with pytest.raises(RuntimeError):
        await failing.athrow(RuntimeError("boom"))

    async with session_factory() as check:
        names = set(await check.scalars(select(Projects.name)))
    assert "committed" in names and "rolled-back" not in names
