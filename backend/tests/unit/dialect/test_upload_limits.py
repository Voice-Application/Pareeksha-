"""Dialect upload limits (row cap, repeated members, ZIP bombs) and the cap on upload routes."""

from __future__ import annotations

import io
import uuid
import wave
import zipfile
from collections.abc import AsyncIterator

import httpx
import pytest

from pareeksha.api.errors import ApiError
from pareeksha.api.main import app
from pareeksha.dialect import manifest
from pareeksha.dialect.manifest import MAX_MANIFEST_ROWS, collect_clips, open_zip, parse_manifest

HEADER = "file,reference_text,language,dialect_label,speaker_id,consent,domain_terms\n"


def wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * 8000)
    return buf.getvalue()


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def row(name: str, n: int = 0) -> str:
    return f"{name},hello,kn-IN,kn-north,s{n},true,\n"


def test_manifest_row_cap() -> None:
    at_cap = HEADER + "".join(row(f"{i}.wav", i) for i in range(MAX_MANIFEST_ROWS))
    assert len(parse_manifest(at_cap.encode())) == MAX_MANIFEST_ROWS
    with pytest.raises(ApiError) as err:
        parse_manifest((at_cap + row("extra.wav")).encode())
    assert err.value.status_code == 413
    assert "rows" in err.value.message


def test_one_member_referenced_by_several_rows_is_read_once() -> None:
    archive = open_zip(zip_bytes({"a.wav": wav()}))
    opened: list[str] = []
    real_open = archive.open

    def counting_open(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        opened.append(str(name))
        return real_open(name, *args, **kwargs)

    archive.open = counting_open  # type: ignore[method-assign]
    body = row("a.wav", 1) + row("./a.wav", 2) + row("clips/a.wav", 3) + row("a.wav", 4)
    clips, rejected = collect_clips(parse_manifest((HEADER + body).encode()), archive)
    assert len(clips) == 1
    assert opened == ["a.wav"]
    assert [r.row for r in rejected] == [2, 3, 4]
    assert all("duplicate file" in r.reason for r in rejected)


def test_zip_declaring_too_much_data_is_refused_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(manifest, "MAX_ZIP_UNCOMPRESSED_BYTES", 10_000)
    bomb = zip_bytes({"a.wav": b"\x00" * 50_000})  # tiny when compressed
    assert len(bomb) < 1000
    with pytest.raises(ApiError) as err:
        open_zip(bomb)
    assert err.value.status_code == 413


def test_zip_listing_too_many_members_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manifest, "MAX_ZIP_MEMBERS", 3)
    with pytest.raises(ApiError) as err:
        open_zip(zip_bytes({f"{i}.wav": b"x" for i in range(4)}))
    assert err.value.status_code == 413


def test_open_zip_accepts_a_file_object() -> None:
    archive = open_zip(io.BytesIO(zip_bytes({"a.wav": wav()})))
    assert archive.namelist() == ["a.wav"]


@pytest.mark.parametrize(
    ("path", "limit"),
    [
        (f"/api/v1/dialect-datasets/{uuid.uuid4()}/samples", 202 * 1024 * 1024),
        ("/api/v1/audits", 10 * 1024 * 1024),
        (f"/api/v1/noise-profiles/{uuid.uuid4()}/preview", 10 * 1024 * 1024),
    ],
)
async def test_multipart_routes_refuse_oversized_bodies_before_parsing(
    path: str, limit: int
) -> None:
    boundary = "b0undary"
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}

    async def body() -> AsyncIterator[bytes]:
        sent = 0
        disposition = 'Content-Disposition: form-data; name="file"; filename="a"'
        yield f"--{boundary}\r\n{disposition}\r\n\r\n".encode()
        while sent <= limit + 2 * 1024 * 1024:
            yield b"x" * 65536
            sent += 65536

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        streamed = await client.post(path, content=body(), headers=headers)
        declared = await client.post(
            path, content=b"", headers={**headers, "Content-Length": str(limit + 2 * 1024 * 1024)}
        )
    assert streamed.status_code == 413 and declared.status_code == 413
    assert streamed.json()["error"]["code"] == "file_too_large"
