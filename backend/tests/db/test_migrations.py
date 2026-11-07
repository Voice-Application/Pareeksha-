"""Alembic ``0001_initial`` against real Postgres: tables, columns and indexes match schema.sql."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import psycopg
import pytest
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from pareeksha.db.models import Base
from tests.conftest import BACKEND, _migrated_database, alembic_config

SCHEMA_SQL = BACKEND.parent / "docs" / "schema.sql"
MIGRATION_SQL = BACKEND / "alembic" / "sql" / "0001_initial.sql"

# Tables added by later Alembic revisions; not part of docs/schema.sql v0.2.
POST_V02_TABLES = {"users", "llm_settings", "prompt_versions"}


def _documented_tables() -> set[str]:
    return set(re.findall(r"^CREATE TABLE (\w+)", SCHEMA_SQL.read_text(), flags=re.MULTILINE))


def _documented_indexes() -> set[str]:
    text = SCHEMA_SQL.read_text()
    return set(re.findall(r"^CREATE (?:UNIQUE )?INDEX (\w+)", text, flags=re.MULTILINE))


def _live(conn: Connection) -> tuple[set[str], dict[str, set[str]], set[str]]:
    insp = inspect(conn)
    tables = set(insp.get_table_names()) - {"alembic_version"}
    columns = {t: {c["name"] for c in insp.get_columns(t)} for t in tables}
    indexes = {i["name"] for t in tables for i in insp.get_indexes(t) if i["name"]}
    return tables, columns, indexes


def test_migration_sql_is_a_copy_of_the_documented_schema() -> None:
    assert MIGRATION_SQL.read_bytes() == SCHEMA_SQL.read_bytes()


async def test_tables_columns_and_indexes_match_schema_sql(engine: AsyncEngine) -> None:
    """The live schema has the documented tables and indexes, and the models mirror its columns."""
    async with engine.connect() as conn:
        tables, columns, indexes = await conn.run_sync(_live)
    assert tables - POST_V02_TABLES == _documented_tables()
    assert len(tables - POST_V02_TABLES) == 29
    assert indexes >= _documented_indexes()
    # The SQLAlchemy models mirror the live database exactly.
    assert set(Base.metadata.tables) == tables
    for name, table in Base.metadata.tables.items():
        assert {c.name for c in table.columns} == columns[name], name


async def test_partial_unique_index_and_checks_are_enforced(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        rows = await conn.exec_driver_sql(
            "select indexname, indexdef from pg_indexes where schemaname = 'public'"
        )
        defs = {str(r["indexname"]): str(r["indexdef"]) for r in rows.mappings().all()}
    assert "WHERE is_active" in defs["one_active_rubric"]
    assert "WHERE (published_at IS NULL)" in defs["outbox_unpublished"]


def test_downgrade_then_upgrade_round_trips(database_url: str) -> None:
    cfg = alembic_config(database_url)
    sync_url = database_url.replace("+psycopg", "")
    command.downgrade(cfg, "base")
    with psycopg.connect(sync_url) as conn:
        remaining = conn.execute(
            "select count(*) from information_schema.tables where table_schema = 'public' "
            "and table_name <> 'alembic_version'"
        ).fetchone()
    assert remaining == (0,)
    command.upgrade(cfg, "head")
    with psycopg.connect(sync_url) as conn:
        assert conn.execute("select count(*) from projects").fetchone() == (0,)


def test_downgrade_0004_keeps_prompt_agents_and_drops_new_checks() -> None:
    """Rows using 'prompt' / 'no_unexpected_tool' must not block re-adding the old CHECKs."""
    for url in _migrated_database():
        cfg = alembic_config(url)
        sync_url = url.replace("+psycopg", "")
        with psycopg.connect(sync_url, autocommit=True) as conn:
            project = conn.execute("insert into projects (name) values ('p') returning id")
            project_id = project.fetchone()[0]  # type: ignore[index]
            agent = conn.execute(
                "insert into agents (project_id, name, adapter, endpoint_url) "
                "values (%s, 'a', 'prompt', 'prompt://x') returning id",
                (project_id,),
            )
            agent_id = agent.fetchone()[0]  # type: ignore[index]
            call = conn.execute(
                "insert into calls (project_id, agent_id, source) values (%s, %s, 'upload') "
                "returning id",
                (project_id, agent_id),
            )
            call_id = call.fetchone()[0]  # type: ignore[index]
            conn.execute(
                "insert into deterministic_checks (call_id, check_type, check_key) "
                "values (%s, 'no_unexpected_tool', 'k')",
                (call_id,),
            )
        command.downgrade(cfg, "0003")
        with psycopg.connect(sync_url) as conn:
            row = conn.execute("select adapter, archived from agents").fetchone()
            checks = conn.execute("select count(*) from deterministic_checks").fetchone()
        assert row == ("audio_v1", True)
        assert checks == (0,)
        command.upgrade(cfg, "head")


@pytest.mark.parametrize("run", [1, 2])
def test_migrate_script_is_idempotent(database_url: str, run: int) -> None:
    result = subprocess.run(
        ["sh", str(BACKEND / "alembic_migrate.sh")],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": database_url, "PYTHONPATH": str(BACKEND)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert Path(BACKEND / "alembic.ini").exists()
