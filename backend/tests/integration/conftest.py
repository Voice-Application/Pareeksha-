"""Integration fixtures: a real Postgres database with the Kafka plumbing tables."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.deps import get_blob_store
from pareeksha.api.main import app
from pareeksha.db.session import get_session_factory
from pareeksha.evaluation.rubric import RUBRIC_VERSION
from pareeksha.events.settings import libpq_url
from pareeksha.storage.blob import LocalBlobStore
from tests.conftest import Tenant, new_tenant
from tests.integration.audit_support import RUBRIC_SQL, transaction
from tests.integration.support import prepare_database


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    prepare_database()


@pytest.fixture
def blobs(tmp_path: Path) -> Iterator[LocalBlobStore]:
    """Recordings go to a temp directory instead of ``DATA_DIR``."""
    store = LocalBlobStore(tmp_path / "blobs")
    app.dependency_overrides[get_blob_store] = lambda: store
    yield store
    app.dependency_overrides.pop(get_blob_store, None)


@pytest.fixture
async def rubric(database_url: str) -> None:
    """The active rubric version row the evaluator stores its evaluations against."""
    async with transaction(database_url) as ctx:
        await ctx.tx.execute(RUBRIC_SQL, (RUBRIC_VERSION,))


@pytest.fixture
async def private_api(
    fresh_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[AsyncClient, Tenant, async_sessionmaker[AsyncSession]]]:
    """The app over its own empty migrated database.

    For tests of global figures (DLQ order, usage totals, outbox backlog): rows written there
    cannot leak into the shared session database that other tests assert on.
    """
    app.dependency_overrides[get_session_factory] = lambda: fresh_session_factory
    tenant = await new_tenant(fresh_session_factory)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, tenant, fresh_session_factory
    app.dependency_overrides.pop(get_session_factory, None)


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``DATA_DIR`` for the API and workers under test (clips, reports)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
async def pg(database_url: str) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """A psycopg connection to the migrated test database (what a consumer's ``ctx.tx`` is)."""
    conn = await psycopg.AsyncConnection.connect(libpq_url(database_url), autocommit=True)
    yield conn
    await conn.close()
