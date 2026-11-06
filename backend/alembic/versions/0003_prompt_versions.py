"""prompt_versions table, 'prompt' adapter, 'no_unexpected_tool' check type

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_ADAPTERS = ["audio_v1", "pipecat", "livekit", "vapi"]
_CHECKS = [
    "disclosure_present",
    "forbidden_absent",
    "language_match",
    "tool_calls_expected",
    "no_loop",
    "amount_confirmed",
]


def _any(col: str, values: list[str]) -> str:
    return f"{col} = ANY (ARRAY[{', '.join(f'{v!r}::text' for v in values)}])"


def _swap_checks(adapters: list[str], checks: list[str]) -> None:
    op.drop_constraint("agents_adapter_check", "agents", type_="check")
    op.create_check_constraint("agents_adapter_check", "agents", _any("adapter", adapters))
    op.drop_constraint(
        "deterministic_checks_check_type_check", "deterministic_checks", type_="check"
    )
    op.create_check_constraint(
        "deterministic_checks_check_type_check",
        "deterministic_checks",
        _any("check_type", checks),
    )


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("tools", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("max_tool_rounds", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column("rag_config", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("note", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], ondelete="CASCADE", name="prompt_versions_agent_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            ondelete="CASCADE",
            name="prompt_versions_project_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="prompt_versions_pkey"),
        sa.UniqueConstraint("agent_id", "version", name="prompt_versions_agent_id_version_key"),
    )
    op.create_index("prompt_versions_agent_id_idx", "prompt_versions", ["agent_id"])
    _swap_checks([*_ADAPTERS, "prompt"], [*_CHECKS, "no_unexpected_tool"])


def downgrade() -> None:
    # The old CHECKs reject these values. Deleting prompt agents would have to cascade through
    # calls / test_runs (no ON DELETE CASCADE), so keep them as archived, inert audio_v1 agents.
    op.execute("DELETE FROM deterministic_checks WHERE check_type = 'no_unexpected_tool'")
    op.execute("UPDATE agents SET adapter = 'audio_v1', archived = true WHERE adapter = 'prompt'")
    op.drop_table("prompt_versions")
    _swap_checks(_ADAPTERS, _CHECKS)
