"""Integration fixtures: a real Postgres database with the Kafka plumbing tables."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from pareeksha.api.deps import get_blob_store
from pareeksha.api.main import app
from pareeksha.evaluation.rubric import RUBRIC_VERSION
from pareeksha.storage.blob import LocalBlobStore
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
