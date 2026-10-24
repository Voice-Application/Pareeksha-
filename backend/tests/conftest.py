"""Shared fixtures. Real-Postgres (no mocks): a throwaway database migrated with Alembic.

Needs a reachable Postgres (``docker compose up -d postgres``). The server comes from
``TEST_DATABASE_URL`` / ``DATABASE_URL`` (default: the compose Postgres on localhost); each test
session creates ``pareeksha_test_<random>`` on it and drops it afterwards.
"""

from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from pareeksha.api.auth import generate_api_key
from pareeksha.api.main import app
from pareeksha.db.models import ApiKeys, Projects
from pareeksha.db.session import get_session_factory, make_engine

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_URL = "postgresql+psycopg://pareeksha:pareeksha@localhost:5432/pareeksha"


def _server_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_URL


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """URL of a fresh database migrated to head with Alembic."""
    yield from _migrated_database()


@pytest.fixture
async def fresh_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A private, empty (migrated) database for tests that need to start from nothing."""
    for url in _migrated_database():
        eng = make_engine(url, poolclass=NullPool)
        yield async_sessionmaker(eng, expire_on_commit=False)
        await eng.dispose()


def _migrated_database() -> Iterator[str]:
    base = make_url(_server_url())
    name = f"pareeksha_test_{secrets.token_hex(4)}"
    admin = base.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = base.set(database=name).render_as_string(hide_password=False)
    command.upgrade(alembic_config(url), "head")
    yield url
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = make_engine(database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------- API fixtures
@dataclass
class Tenant:
    """A project with an admin key and a read-only key, isolated from every other test's data."""

    project_id: uuid.UUID
    admin: dict[str, str]
    read: dict[str, str]


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


async def make_api_key(
    factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID, scopes: list[str]
) -> str:
    key, prefix, key_hash = generate_api_key()
    async with factory() as session:
        session.add(
            ApiKeys(
                project_id=project_id, name="test", prefix=prefix, key_hash=key_hash, scopes=scopes
            )
        )
        await session.commit()
    return key


async def new_tenant(factory: async_sessionmaker[AsyncSession]) -> Tenant:
    async with factory() as session:
        project = Projects(name=f"p-{uuid.uuid4().hex[:8]}")
        session.add(project)
        await session.commit()
    admin = await make_api_key(factory, project.id, ["admin"])
    read = await make_api_key(factory, project.id, ["read"])
    return Tenant(project.id, bearer(admin), bearer(read))


@pytest.fixture
async def tenant(session_factory: async_sessionmaker[AsyncSession]) -> Tenant:
    return await new_tenant(session_factory)


@pytest.fixture
async def other_tenant(session_factory: async_sessionmaker[AsyncSession]) -> Tenant:
    """A second project, to prove that keys only ever see their own project's rows."""
    return await new_tenant(session_factory)


@pytest.fixture
async def api(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """The real app over ASGI, wired to the throwaway Postgres (real key lookup, no mocks)."""
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.pop(get_session_factory, None)
