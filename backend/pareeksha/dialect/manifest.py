"""Manifest import (FR-DI-1, NFR-9): CSV rows plus a ZIP of clips; no consent, no import.

Header: ``file,reference_text,language,dialect_label,speaker_id,consent,domain_terms``.
``domain_terms`` is optional and separated by ``|`` (or ``;``). Rows are validated one by one; a
bad row is rejected with a reason and the rest still import (``accepted`` / ``rejected`` in the
response).
"""

from __future__ import annotations

import csv
import io
import posixpath
import wave
import zipfile
from dataclasses import dataclass
from typing import IO

from pareeksha.api.errors import ApiError

REQUIRED_COLUMNS = (
    "file",
    "reference_text",
    "language",
    "dialect_label",
    "speaker_id",
    "consent",
)
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ZIP_BYTES = 200 * 1024 * 1024
MAX_CLIP_BYTES = 10 * 1024 * 1024
MAX_CLIP_SECONDS = 60.0
#: The largest documented dataset (DIALECT-02) is 110 clips; ten times that leaves headroom.
MAX_MANIFEST_ROWS = 1000
#: Declared uncompressed size of the whole ZIP (read from its directory, so a decompression bomb
#: is refused before any member is inflated), and the number of members it may list.
MAX_ZIP_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_ZIP_MEMBERS = 5000
_TRUE = {"true", "yes", "y", "1"}
_LANGUAGE = (
    "kn-IN",
    "hi-IN",
    "en-IN",
    "ta-IN",
    "te-IN",
    "ml-IN",
    "mr-IN",
    "bn-IN",
    "gu-IN",
    "pa-IN",
)


@dataclass(frozen=True)
class ManifestRow:
    file: str
    reference_text: str
    language: str
    dialect_label: str
    speaker_id: str
    domain_terms: list[str]


@dataclass(frozen=True)
class RowRejection:
    row: int
    reason: str


@dataclass(frozen=True)
class Clip:
    row: ManifestRow
    wav: bytes
    duration_ms: int


def _split_terms(raw: str) -> list[str]:
    parts = [p.strip() for chunk in raw.split("|") for p in chunk.split(";")]
    return [p for p in parts if p]


def clip_duration_ms(data: bytes) -> int:
    """Duration of a WAV clip; raises ``ValueError`` for anything that is not readable audio."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            frames, rate = w.getnframes(), w.getframerate()
            if w.getsampwidth() != 2:
                raise ValueError("only 16-bit PCM WAV is supported")
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"not a readable WAV file: {exc}") from exc
    if frames == 0 or rate <= 0:
        raise ValueError("the clip contains no audio")
    seconds: float = frames / rate
    if seconds > MAX_CLIP_SECONDS:
        raise ValueError(f"clip is longer than {MAX_CLIP_SECONDS:.0f} s")
    return int(seconds * 1000 + 0.5)


def parse_manifest(csv_bytes: bytes) -> list[tuple[int, dict[str, str]]]:
    """``[(row_number, fields)]``; row numbers are 1-based data rows (the header is not counted)."""
    if len(csv_bytes) > MAX_MANIFEST_BYTES:
        raise ApiError(413, "file_too_large", "Manifest is larger than 2 MB")
    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(400, "validation_error", "Manifest must be UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ApiError(
            400, "validation_error", f"Manifest header is missing columns: {', '.join(missing)}"
        )
    reader.fieldnames = header
    parsed: list[tuple[int, dict[str, str]]] = []
    for n, row in enumerate(reader, start=1):
        if n > MAX_MANIFEST_ROWS:
            raise ApiError(
                413,
                "file_too_large",
                f"Manifest has more than {MAX_MANIFEST_ROWS} rows",
                {"max_rows": MAX_MANIFEST_ROWS},
            )
        parsed.append((n, {k: (v or "").strip() for k, v in row.items() if k}))
    return parsed


def validate_row(fields: dict[str, str]) -> ManifestRow | str:
    """The row, or the reason it is rejected. Consent must be an explicit yes."""
    if fields.get("consent", "").lower() not in _TRUE:
        return "consent must be true"
    for column in ("file", "reference_text", "language", "dialect_label", "speaker_id"):
        if not fields.get(column):
            return f"{column} is empty"
    if fields["language"] not in _LANGUAGE:
        return f"language must be one of {', '.join(_LANGUAGE)}"
    return ManifestRow(
        file=fields["file"],
        reference_text=fields["reference_text"],
        language=fields["language"],
        dialect_label=fields["dialect_label"],
        speaker_id=fields["speaker_id"],
        domain_terms=_split_terms(fields.get("domain_terms", "")),
    )


def open_zip(source: bytes | IO[bytes]) -> zipfile.ZipFile:
    """Open the clips ZIP (bytes or a seekable file) after checking its size and, from the
    directory, how much it declares to expand to."""
    fileobj = io.BytesIO(source) if isinstance(source, bytes) else source
    size = fileobj.seek(0, io.SEEK_END)
    fileobj.seek(0)
    if size > MAX_ZIP_BYTES:
        raise ApiError(413, "file_too_large", "Clips ZIP is larger than 200 MB")
    try:
        archive = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile as exc:
        raise ApiError(400, "validation_error", "clips must be a ZIP archive") from exc
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_MEMBERS or sum(i.file_size for i in infos) > (
        MAX_ZIP_UNCOMPRESSED_BYTES
    ):
        archive.close()
        raise ApiError(
            413,
            "file_too_large",
            "Clips ZIP expands to more than 512 MB or lists too many files",
        )
    return archive


def _find_member(archive: zipfile.ZipFile, name: str) -> str | None:
    """Manifest ``file`` -> ZIP member; ZIP-slip safe (only plain relative names, no ``..``)."""
    clean = posixpath.normpath(name.replace("\\", "/"))
    if clean.startswith(("/", "..")) or clean == ".":
        return None
    names = set(archive.namelist())
    if clean in names:
        return clean
    base = posixpath.basename(clean)  # tolerate a clips/ prefix inside the archive
    matches = [n for n in names if posixpath.basename(n) == base and not n.endswith("/")]
    return matches[0] if len(matches) == 1 else None


def collect_clips(
    rows: list[tuple[int, dict[str, str]]], archive: zipfile.ZipFile
) -> tuple[list[Clip], list[RowRejection]]:
    """Validate every row and read its clip from the archive."""
    clips: list[Clip] = []
    rejected: list[RowRejection] = []
    seen: set[str] = set()  # ZIP members already read: one member is read once
    for number, fields in rows:
        parsed = validate_row(fields)
        if isinstance(parsed, str):
            rejected.append(RowRejection(number, parsed))
            continue
        member = _find_member(archive, parsed.file)
        if member is None:
            rejected.append(RowRejection(number, f"file {parsed.file} not found in the ZIP"))
            continue
        if member in seen or parsed.file in seen:  # also "a.wav" vs "./a.wav" vs "clips/a.wav"
            rejected.append(RowRejection(number, f"duplicate file {parsed.file}"))
            continue
        info = archive.getinfo(member)
        if info.file_size > MAX_CLIP_BYTES:
            rejected.append(RowRejection(number, "clip is larger than 10 MB"))
            continue
        with archive.open(member) as handle:
            data = handle.read(MAX_CLIP_BYTES + 1)
        if len(data) > MAX_CLIP_BYTES:
            rejected.append(RowRejection(number, "clip is larger than 10 MB"))
            continue
        try:
            duration = clip_duration_ms(data)
        except ValueError as exc:
            rejected.append(RowRejection(number, str(exc)))
            continue
        seen.update((member, parsed.file))
        clips.append(Clip(parsed, data, duration))
    return clips, rejected
