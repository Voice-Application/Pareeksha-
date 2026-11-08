"""Whatever goes wrong in a build, the index ends ``ready`` or ``failed``, never ``pending``."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.events.topics import MAX_ATTEMPTS
from pareeksha.rag import indexing
from tests.conftest import Tenant
from tests.integration.test_indexer import FakeEmbedder, _get, _kb, _request, _run

pytestmark = pytest.mark.usefixtures("blobs")


async def pending_index(api: AsyncClient, tenant: Tenant) -> tuple[str, str]:
    kb_id = await _kb(api, tenant)
    idx = (await _request(api, tenant, kb_id)).json()
    return kb_id, str(idx["id"])


async def test_unexpected_error_fails_the_index_instead_of_leaving_it_pending(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    kb_id, index_id = await pending_index(api, tenant)
    await _run(session_factory, pg, index_id, FakeEmbedder(RuntimeError("onnx exploded")))
    done = await _get(api, tenant, kb_id, index_id)
    assert done["status"] == "failed" and "onnx exploded" in done["error"]


async def test_sql_error_in_a_build_still_ends_failed(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kb_id, index_id = await pending_index(api, tenant)

    async def broken(conn: Any, *a: Any, **k: Any) -> Any:
        await conn.execute("SELECT * FROM table_that_does_not_exist")

    monkeypatch.setattr(indexing, "_build", broken)
    # the aborted statement must not poison the surrounding transaction (the ``failed`` update)
    await _run(session_factory, pg, index_id, FakeEmbedder())
    done = await _get(api, tenant, kb_id, index_id)
    assert done["status"] == "failed" and "table_that_does_not_exist" in done["error"]


async def test_transient_error_retries_then_fails_on_the_last_attempt(
    api: AsyncClient,
    tenant: Tenant,
    session_factory: async_sessionmaker[AsyncSession],
    pg: psycopg.AsyncConnection[Any],
) -> None:
    kb_id, index_id = await pending_index(api, tenant)
    flaky = FakeEmbedder(ConnectionResetError("reset by peer"))
    with pytest.raises(ConnectionResetError):
        await _run(session_factory, pg, index_id, flaky, attempt=1)
    assert (await _get(api, tenant, kb_id, index_id))["status"] == "pending"  # retried later
    await _run(session_factory, pg, index_id, flaky, attempt=MAX_ATTEMPTS)
    assert (await _get(api, tenant, kb_id, index_id))["status"] == "failed"
