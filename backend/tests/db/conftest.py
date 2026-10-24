"""Real-Postgres fixtures (no mocks): a throwaway database migrated with Alembic.

Needs a reachable Postgres (``docker compose up -d postgres``). The server comes from
``TEST_DATABASE_URL`` / ``DATABASE_URL`` (default: the compose Postgres on localhost); each test
session creates ``pareeksha_test_<random>`` on it and drops it afterwards.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from pareeksha.db.session import make_engine

BACKEND = Path(__file__).resolve().parents[2]
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
