"""Local blob store: round trip, atomic write, path safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from pareeksha.storage import BlobNotFoundError, LocalBlobStore, blob_store_from_env


async def test_round_trip_and_overwrite(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    assert not await store.exists("uploads/a/original.wav")
    await store.put("uploads/a/original.wav", b"one")
    await store.put("uploads/a/original.wav", b"two")
    assert await store.exists("uploads/a/original.wav")
    assert await store.get("uploads/a/original.wav") == b"two"
    assert not list(tmp_path.rglob("*.tmp"))


async def test_missing_blob() -> None:
    store = LocalBlobStore("/nonexistent-root-for-test")
    with pytest.raises(BlobNotFoundError):
        await store.get("uploads/none/original.wav")


@pytest.mark.parametrize(
    "key", ["", "/etc/passwd", "../outside", "a/../../outside", "a\\b", "a\x00b"]
)
async def test_unsafe_keys_are_refused(tmp_path: Path, key: str) -> None:
    store = LocalBlobStore(tmp_path)
    with pytest.raises(ValueError, match="blob key"):
        await store.put(key, b"x")
    with pytest.raises(ValueError, match="blob key"):
        await store.exists(key)


def test_data_dir_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert blob_store_from_env().root == tmp_path.resolve()
    monkeypatch.delenv("DATA_DIR")
    assert blob_store_from_env().root == Path("./data/runtime").resolve()
