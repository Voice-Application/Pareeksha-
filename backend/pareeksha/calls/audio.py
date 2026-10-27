"""Serving a recording from ``DATA_DIR`` with HTTP Range support (API-04).

``calls.recording_*`` hold paths relative to ``DATA_DIR``. A path that resolves outside it is
refused (404, never revealed), so a bad row cannot expose other files.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import Response

from pareeksha.api.errors import ApiError

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def resolve(blob_path: str) -> Path:
    """The file for a stored path, or 404 when it is missing or outside ``DATA_DIR``."""
    data_dir = os.environ.get("DATA_DIR")
    if not data_dir:
        raise ApiError(404, "not_found", "Recordings are not available: DATA_DIR is not set")
    root = Path(data_dir).resolve()
    path = (root / blob_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ApiError(404, "not_found", "The recording file is not available")
    return path


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """``(first, last)`` inclusive for a single ``bytes=`` range; ``None`` for a syntax we ignore.

    Raises 416 when the range cannot be satisfied. Multi-range requests are answered with the
    whole file (permitted by RFC 9110).
    """
    match = _RANGE.match(header.strip())
    if match is None:
        return None
    start_s, end_s = match.groups()
    if not start_s and not end_s:
        return None
    if not start_s:  # suffix: the last N bytes
        length = int(end_s)
        if length == 0:
            raise _unsatisfiable(size)
        return max(size - length, 0), size - 1
    start = int(start_s)
    end = min(int(end_s), size - 1) if end_s else size - 1
    if start >= size or end < start:
        raise _unsatisfiable(size)
    return start, end


def _unsatisfiable(size: int) -> ApiError:
    return ApiError(
        416,
        "range_not_satisfiable",
        "The requested range is outside the recording",
        {"size": size},
        headers={"Content-Range": f"bytes */{size}"},
    )


def audio_response(blob_path: str, range_header: str | None) -> Response:
    """200 with the whole WAV, or 206 with the requested byte range."""
    path = resolve(blob_path)
    size = path.stat().st_size
    base = {"Accept-Ranges": "bytes"}
    byte_range = parse_range(range_header, size) if range_header else None
    with path.open("rb") as f:
        if byte_range is None:
            return Response(f.read(), media_type="audio/wav", headers=base)
        first, last = byte_range
        f.seek(first)
        body = f.read(last - first + 1)
    return Response(
        body,
        status_code=206,
        media_type="audio/wav",
        headers={**base, "Content-Range": f"bytes {first}-{last}/{size}"},
    )
