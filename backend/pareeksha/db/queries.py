"""Small SQLAlchemy helpers shared by the API and workers."""

from __future__ import annotations

from typing import Any

_distinct_on: Any
try:  # SQLAlchemy 2.1+: the DISTINCT ON extension; 2.0 spells it ``.distinct(*columns)``
    from sqlalchemy.dialects.postgresql import distinct_on as _distinct_on
except ImportError:  # pragma: no cover - depends on the installed SQLAlchemy
    _distinct_on = None


def distinct_on(stmt: Any, *columns: Any) -> Any:
    """``SELECT DISTINCT ON (columns) ...`` for a Select; ORDER BY must start with the columns.

    Returns the statement (typed ``Any``: the row type is unchanged, only the rows are deduped).
    """
    if _distinct_on is None:  # pragma: no cover
        return stmt.distinct(*columns)
    return stmt.ext(_distinct_on(*columns))
