"""Integration fixtures: a real Postgres database with the Kafka plumbing tables."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pareeksha.api.main import app
from pareeksha.db.session import get_session_factory
from tests.conftest import Tenant, new_tenant
from tests.integration.support import prepare_database


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    prepare_database()


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
