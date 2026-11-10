"""'responsive' check type

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_CHECKS = [
    "disclosure_present",
    "forbidden_absent",
    "language_match",
    "tool_calls_expected",
    "no_loop",
    "amount_confirmed",
    "no_unexpected_tool",
]


def _any(col: str, values: list[str]) -> str:
    """The CHECK constraint expression allowing ``col`` to be one of ``values`` (text literals)."""
    return f"{col} = ANY (ARRAY[{', '.join(f'{v!r}::text' for v in values)}])"


def _swap_checks(checks: list[str]) -> None:
    op.drop_constraint(
        "deterministic_checks_check_type_check", "deterministic_checks", type_="check"
    )
    op.create_check_constraint(
        "deterministic_checks_check_type_check",
        "deterministic_checks",
        _any("check_type", checks),
    )


def upgrade() -> None:
    _swap_checks([*_CHECKS, "responsive"])


def downgrade() -> None:
    # The old CHECK rejects this value.
    op.execute("DELETE FROM deterministic_checks WHERE check_type = 'responsive'")
    _swap_checks(_CHECKS)
