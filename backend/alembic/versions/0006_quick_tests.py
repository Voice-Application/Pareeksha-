"""Quick tests: "paste a prompt and test it" (one row per test; the agent, scenarios and run are
ordinary rows it points at)

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _fk(col: str, target: str, ondelete: str = "CASCADE") -> sa.ForeignKeyConstraint:
    """Foreign key ``quick_tests.<col>`` -> ``<target>.id`` named like the other tables' keys."""
    return sa.ForeignKeyConstraint(
        [col], [f"{target}.id"], ondelete=ondelete, name=f"quick_tests_{col}_fkey"
    )


def upgrade() -> None:
    """Create ``quick_tests``."""
    op.create_table(
        "quick_tests",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("kb_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_details", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=False),
        sa.Column("verdicts", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("improvement", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _fk("project_id", "projects"),
        _fk("agent_id", "agents"),
        _fk("run_id", "test_runs"),
        _fk("parent_id", "quick_tests", "SET NULL"),
        _fk("kb_id", "knowledge_bases", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="quick_tests_pkey"),
    )
    op.create_index("quick_tests_project_created", "quick_tests", ["project_id", "created_at"])


def downgrade() -> None:
    """Drop ``quick_tests``."""
    op.drop_index("quick_tests_project_created", table_name="quick_tests")
    op.drop_table("quick_tests")
