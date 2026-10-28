"""initial schema (docs/schema.sql v0.2)

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# alembic/sql/0001_initial.sql is a byte-for-byte copy of docs/schema.sql (a test enforces it), so
# the migrated database is exactly the documented schema, including partial indexes and CHECKs.
_SQL = Path(__file__).resolve().parents[1] / "sql" / "0001_initial.sql"

# Order is irrelevant for DROP ... CASCADE.
_TABLES = (
    "api_usage, api_keys, external_refs, integration_deliveries, integrations, dead_letters, "
    "processed_events, outbox_events, dialect_reports, asr_results, dialect_samples, "
    "dialect_datasets, regression_tests, human_reviews, evaluations, deterministic_checks, "
    "call_metrics, tool_calls, turns, calls, run_items, test_runs, rubric_versions, "
    "noise_profiles, personas, scenario_drafts, scenarios, agents, projects"
)


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {_TABLES} CASCADE")
