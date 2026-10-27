"""T-FR-DI-1 / NFR-9: rows without consent=true are rejected; the rest still import."""

from __future__ import annotations

import io
import wave
import zipfile

import pytest

from pareeksha.api.errors import ApiError
from pareeksha.dialect.manifest import collect_clips, open_zip, parse_manifest, validate_row

HEADER = "file,reference_text,language,dialect_label,speaker_id,consent,domain_terms\n"


def wav(seconds: float = 0.5, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(rate * seconds))
    return buf.getvalue()


def archive(files: dict[str, bytes]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return open_zip(buf.getvalue())


def rows(body: str) -> list[tuple[int, dict[str, str]]]:
    return parse_manifest((HEADER + body).encode())


@pytest.mark.parametrize("consent", ["false", "FALSE", "", "no", "0", "maybe"])
def test_row_without_explicit_consent_is_rejected(consent: str) -> None:
    out = validate_row(
        {
            "file": "a.wav",
            "reference_text": "x",
            "language": "kn-IN",
            "dialect_label": "kn-north",
            "speaker_id": "s1",
            "consent": consent,
        }
    )
    assert out == "consent must be true"


def test_import_accepts_consented_rows_and_reports_the_rest_by_row_number() -> None:
    body = (
        "a.wav,ನಮಸ್ಕಾರ,kn-IN,kn-north,s1,true,ಕಂತು|EMI\n"
        "b.wav,hello,kn-IN,kn-north,s2,false,\n"  # no consent
        "c.wav,hi,xx-XX,kn-north,s3,true,\n"  # bad language
        "missing.wav,hi,kn-IN,kn-north,s4,true,\n"  # not in the ZIP
        "d.wav,,kn-IN,kn-north,s5,true,\n"  # empty reference
        "a.wav,again,kn-IN,kn-north,s6,true,\n"  # duplicate file
    )
    z = archive({"a.wav": wav(), "b.wav": wav(), "c.wav": wav(), "d.wav": wav()})
    clips, rejected = collect_clips(rows(body), z)
    assert [c.row.file for c in clips] == ["a.wav"]
    assert clips[0].row.domain_terms == ["ಕಂತು", "EMI"]
    assert clips[0].duration_ms == 500
    assert [(r.row, r.reason) for r in rejected] == [
        (2, "consent must be true"),
        (
            3,
            "language must be one of kn-IN, hi-IN, en-IN, ta-IN, te-IN, ml-IN, mr-IN, bn-IN, "
            "gu-IN, pa-IN",
        ),
        (4, "file missing.wav not found in the ZIP"),
        (5, "reference_text is empty"),
        (6, "duplicate file a.wav"),
    ]


def test_unreadable_or_oversized_audio_is_rejected_per_row() -> None:
    z = archive({"bad.wav": b"not audio", "long.wav": wav(61.0, 8000)})
    body = "bad.wav,x,kn-IN,d,s,true,\nlong.wav,x,kn-IN,d,s,true,\n"
    clips, rejected = collect_clips(rows(body), z)
    assert clips == []
    assert "not a readable WAV" in rejected[0].reason
    assert "longer than 60 s" in rejected[1].reason


def test_zip_paths_cannot_escape_and_a_clips_prefix_is_tolerated() -> None:
    z = archive({"clips/a.wav": wav(), "../evil.wav": wav()})
    body = (
        "a.wav,x,kn-IN,d,s1,true,\n../evil.wav,x,kn-IN,d,s2,true,\n/etc/passwd,x,kn-IN,d,s3,true,\n"
    )
    clips, rejected = collect_clips(rows(body), z)
    assert [c.row.file for c in clips] == ["a.wav"]
    assert [r.row for r in rejected] == [2, 3]


def test_manifest_must_have_the_required_columns() -> None:
    with pytest.raises(ApiError) as err:
        parse_manifest(b"file,reference_text\na.wav,x\n")
    assert err.value.status_code == 400
    assert "consent" in err.value.message


def test_manifest_must_be_utf8_and_small() -> None:
    with pytest.raises(ApiError) as err:
        parse_manifest(b"\xff\xfe\x00")
    assert err.value.status_code == 400
    with pytest.raises(ApiError) as big:
        parse_manifest(b"x" * (2 * 1024 * 1024 + 1))
    assert big.value.status_code == 413


def test_clips_must_be_a_zip() -> None:
    with pytest.raises(ApiError) as err:
        open_zip(b"definitely not a zip")
    assert err.value.status_code == 400
