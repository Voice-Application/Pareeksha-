"""Integration fixtures: a real Postgres database with the Kafka plumbing tables."""

from __future__ import annotations

import pytest

from tests.integration.support import prepare_database


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    prepare_database()
