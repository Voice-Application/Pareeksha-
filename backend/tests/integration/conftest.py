"""Integration fixtures: a real Postgres database with the Kafka plumbing tables."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from pareeksha.events.settings import libpq_url
from tests.integration.support import prepare_database


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    prepare_database()


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
