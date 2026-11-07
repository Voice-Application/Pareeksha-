"""build_index fails closed when the knowledge base (or its local_only flag) cannot be read."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from pareeksha.rag.indexing import build_index
from pareeksha.schemas.rag import ChunkingConfig, EmbeddingConfig

HOSTED = EmbeddingConfig(provider="openai", model="text-embedding-3-small").model_dump(mode="json")


class Cur:
    def __init__(self, row: Any) -> None:
        self.row = row

    async def fetchone(self) -> Any:
        return self.row


class Tx:
    async def __aenter__(self) -> Tx:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class FakeConn:
    """Answers the two SELECTs of build_index with the given rows and records every statement."""

    def __init__(self, kb_row: tuple[Any, ...] | None) -> None:
        index_row: tuple[Any, ...] = (
            "pending",
            uuid.uuid4(),
            ChunkingConfig().model_dump(mode="json"),
            HOSTED,
            [],
        )
        self.selects = [index_row, kb_row]
        self.writes: list[tuple[str, Any]] = []

    async def execute(self, sql: str, params: Any = ()) -> Cur:
        if sql.lstrip().startswith("SELECT"):
            return Cur(self.selects.pop(0))
        self.writes.append((sql, params))
        return Cur(None)

    def transaction(self) -> Tx:
        return Tx()


def never_embedder(*_: Any) -> Any:
    raise AssertionError("a hosted embedder must not be built for a local-only knowledge base")


@pytest.mark.parametrize("kb_row", [None, (None, None)], ids=["no-kb-row", "no-flag"])
async def test_unreadable_kb_is_treated_as_local_only(kb_row: tuple[Any, ...] | None) -> None:
    conn = FakeConn(kb_row)
    await build_index(conn, uuid.uuid4(), embedder_for=never_embedder)  # type: ignore[arg-type]
    assert len(conn.writes) == 1  # not left pending: marked failed, nothing else touched
    sql, params = conn.writes[0]
    assert "status = 'failed'" in sql and "local-only" in params[0]
