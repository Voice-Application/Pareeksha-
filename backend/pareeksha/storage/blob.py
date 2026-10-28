"""Blob storage for recordings and raw STT JSON (docs/04-system-design.md section 6).

``BlobStore`` is the port; ``LocalBlobStore`` keeps blobs under ``DATA_DIR`` (default
``./data/runtime``). Paths are relative, ``/``-separated keys such as
``uploads/<call_id>/original.wav`` (the strings stored in ``calls.recording_*`` and in
``audit.requested.recording_ref``); a key that would leave the root is refused.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Protocol


class BlobNotFoundError(FileNotFoundError):
    """No blob under that key (permanent for an event that references it)."""


class BlobStore(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...

    async def get(self, key: str) -> bytes: ...

    async def exists(self, key: str) -> bool: ...


class LocalBlobStore:
    """Files below ``root``; blocking file I/O runs in a worker thread."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or "\\" in key or "\x00" in key:
            raise ValueError(f"invalid blob key: {key!r}")
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError(f"blob key escapes the storage root: {key!r}")
        return path

    async def put(self, key: str, data: bytes) -> None:
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # readers never see a half-written blob

        await asyncio.to_thread(write)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise BlobNotFoundError(key) from exc

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)


def blob_store_from_env() -> LocalBlobStore:
    """``DATA_DIR`` (default ``./data/runtime``)."""
    return LocalBlobStore(os.environ.get("DATA_DIR") or "./data/runtime")
