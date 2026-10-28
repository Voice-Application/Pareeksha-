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
    return [
        (n, {k: (v or "").strip() for k, v in row.items() if k})
        for n, row in enumerate(reader, start=1)
    ]


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


def open_zip(zip_bytes: bytes) -> zipfile.ZipFile:
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise ApiError(413, "file_too_large", "Clips ZIP is larger than 200 MB")
    try:
        return zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise ApiError(400, "validation_error", "clips must be a ZIP archive") from exc


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
    seen: set[str] = set()
    for number, fields in rows:
        parsed = validate_row(fields)
        if isinstance(parsed, str):
            rejected.append(RowRejection(number, parsed))
            continue
        if parsed.file in seen:
            rejected.append(RowRejection(number, f"duplicate file {parsed.file}"))
            continue
        member = _find_member(archive, parsed.file)
        if member is None:
            rejected.append(RowRejection(number, f"file {parsed.file} not found in the ZIP"))
            continue
        info = archive.getinfo(member)
        if info.file_size > MAX_CLIP_BYTES:
            rejected.append(RowRejection(number, "clip is larger than 10 MB"))
            continue
        data = archive.read(member)
        try:
            duration = clip_duration_ms(data)
        except ValueError as exc:
            rejected.append(RowRejection(number, str(exc)))
            continue
        seen.add(parsed.file)
        clips.append(Clip(parsed, data, duration))
    return clips, rejected
