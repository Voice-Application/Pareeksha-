"""Text extraction for knowledge-base documents. Pure and blocking: callers run it in a thread."""

from __future__ import annotations

import csv
import io
import json
import unicodedata
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree

MAX_DOCX_BYTES = 50 * 1024 * 1024
MAX_DOCX_RATIO = 100
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_MIMES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".csv": "text/csv",
    ".json": "application/json",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class ExtractionError(Exception):
    """``code`` is ``unsupported_document`` or a reason (``encrypted_pdf``, ``zip_bomb``, ...)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


class _Html(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html(data: bytes) -> str:
    parser = _Html()
    parser.feed(_decode(data))
    parser.close()
    return "".join(parser.parts)


def _csv(data: bytes) -> str:
    rows = csv.DictReader(io.StringIO(_decode(data)))
    return "\n".join(
        "; ".join(f"{k}: {v}" for k, v in row.items() if k is not None) for row in rows
    )


def _json(data: bytes) -> str:
    return json.dumps(json.loads(_decode(data)), indent=2, ensure_ascii=False)


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ExtractionError("encrypted_pdf")
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if sum(i.file_size for i in infos) > MAX_DOCX_BYTES or any(
            i.file_size / max(i.compress_size, 1) > MAX_DOCX_RATIO for i in infos
        ):
            raise ExtractionError("zip_bomb")
        root = ElementTree.fromstring(zf.read("word/document.xml"))
    return "\n".join("".join(t.text or "" for t in p.iter(f"{_W}t")) for p in root.iter(f"{_W}p"))


_EXTRACTORS = {
    ".txt": _decode,
    ".md": _decode,
    ".html": _html,
    ".htm": _html,
    ".csv": _csv,
    ".json": _json,
    ".pdf": _pdf,
    ".docx": _docx,
}


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """``(mime, text)``; raises ``ExtractionError`` for unsupported, encrypted or broken files."""
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    extractor = _EXTRACTORS.get(ext)
    if extractor is None:
        raise ExtractionError("unsupported_document")
    try:
        text = extractor(data)
    except ExtractionError:
        raise
    except Exception as exc:  # pypdf/zipfile/xml/json errors on garbage input
        raise ExtractionError("extraction_failed") from exc
    text = unicodedata.normalize("NFC", text).replace("\x00", "")
    if not text.strip():
        raise ExtractionError("empty_document")
    return _MIMES[ext], text
