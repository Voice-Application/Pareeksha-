"""Shared route dependencies and OpenAPI response helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Query

from pareeksha.schemas.common import ErrorResponse


@dataclass(frozen=True)
class PageParams:
    """``?limit=`` (default 50, max 200) and opaque ``?cursor=``."""

    limit: int = 50
    cursor: str | None = None


def _page_params(
    limit: Annotated[int, Query(ge=1, le=200, description="page size (max 200)")] = 50,
    cursor: Annotated[str | None, Query(description="opaque cursor from next_cursor")] = None,
) -> PageParams:
    return PageParams(limit=limit, cursor=cursor)


Pagination = Annotated[PageParams, Depends(_page_params)]

_DESCRIPTIONS: dict[int, str] = {
    400: "validation_error",
    401: "unauthorized: missing or invalid API key",
    402: "budget_exceeded: estimate above remaining budget",
    403: "forbidden: key lacks the required scope",
    404: "not_found",
    408: "timestamp_out_of_window",
    409: "conflict",
    413: "file_too_large",
    422: "unsupported_audio / unsafe_url",
    502: "upstream_error: Gnani/LLM failed after retries",
}


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entries for the standard error envelope."""
    return {c: {"model": ErrorResponse, "description": _DESCRIPTIONS[c]} for c in codes}


#: Added to every authenticated router.
AUTH_ERRORS = errors(400, 401, 403)


def binary_response(media_type: str, description: str) -> dict[int | str, dict[str, Any]]:
    """``responses=`` entry for a 200 that returns raw bytes (audio) or text (HTML)."""
    schema = (
        {"type": "string"} if media_type == "text/html" else {"type": "string", "format": "binary"}
    )
    return {200: {"description": description, "content": {media_type: {"schema": schema}}}}
