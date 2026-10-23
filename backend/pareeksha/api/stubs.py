"""The ONE shared helper behind every not-yet-implemented route handler.

TL-01 declares every route of docs/06-api-spec.md so ``/openapi.json`` is complete. A handler whose
owning task has not landed calls ``not_implemented("<TASK-ID>")`` and carries a
``# STUB(<TASK-ID>)`` comment naming that task. The owner removes both when implementing the
route. No stub may name TL-01 itself.
"""

from __future__ import annotations

import re
from typing import NoReturn

from pareeksha.api.errors import ApiError

_TASK_ID = re.compile(r"^[A-Z]+-\d{2}$")


def not_implemented(owner: str) -> NoReturn:
    """Respond ``501 not_implemented`` and name the task that will implement the route."""
    if not _TASK_ID.fullmatch(owner) or owner == "TL-01":
        raise ValueError(
            f"owner must be a task ID from docs/AGENTS.md section 7 (not TL-01): {owner!r}"
        )
    raise ApiError(
        501,
        "not_implemented",
        f"This endpoint is not implemented yet (owner task {owner}).",
        {"owner": owner},
    )
