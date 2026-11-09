"""Repair: add api_usage.project_id and dead_letters.project_id where an old 0001 left them out

Revision 0001 (docs/schema.sql v0.2) has both columns, their foreign keys and indexes. A database
first built from an earlier copy of 0001 and then stamped lacks them, and every budget check
(``api_usage.project_id``) fails there. Everything here is IF NOT EXISTS, so on a database that
already has them this revision changes nothing; downgrade leaves them (they belong to 0001).

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_TABLES = ("api_usage", "dead_letters")


def upgrade() -> None:
    """Add the missing column, foreign key and index for each table, only when absent."""
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS project_id uuid")
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint WHERE conname = '{table}_project_id_fkey'
                ) THEN
                    ALTER TABLE {table} ADD CONSTRAINT {table}_project_id_fkey
                        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;
                END IF;
            END $$
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS {table}_project ON {table} (project_id)")


def downgrade() -> None:
    """Nothing to undo: the columns are part of revision 0001."""
