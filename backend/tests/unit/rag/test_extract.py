"""Text extraction: one test per format plus the hostile inputs (Review Focus 1)."""

from __future__ import annotations

import io
import json
import unicodedata
import zipfile

import pytest
from pypdf import PdfWriter

from pareeksha.rag.extract import ExtractionError, extract_text

_DOCX_XML = (
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    "<w:p><w:r><w:t>Hello</w:t></w:r><w:r><w:t> world</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Second</w:t></w:r></w:p></w:body></w:document>"
)


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_txt_and_md() -> None:
    assert extract_text("a.txt", b"plain text") == ("text/plain", "plain text")
    assert extract_text("a.MD", b"# Title")[0] == "text/markdown"


def test_latin1_fallback() -> None:
    assert extract_text("a.txt", "café".encode("latin-1"))[1] == "café"


def test_html_drops_scripts() -> None:
    html = b"<html><style>p{}</style><script>alert(1)</script><p>Keep</p><p>this</p></html>"
    mime, text = extract_text("a.html", html)
    assert mime == "text/html" and "alert" not in text and "p{}" not in text
    assert "Keep" in text and "this" in text


def test_csv_rows() -> None:
    assert extract_text("a.csv", b"name,age\nAsha,30\nRavi,41\n")[1] == (
        "name: Asha; age: 30\nname: Ravi; age: 41"
    )


def test_json_pretty() -> None:
    _, text = extract_text("a.json", b'{"a":1,"b":[2]}')
    assert json.loads(text) == {"a": 1, "b": [2]} and "\n" in text


def test_pdf_text() -> None:
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(200, 200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (Refund policy) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    buf = io.BytesIO()
    writer.write(buf)
    mime, text = extract_text("a.pdf", buf.getvalue())
    assert mime == "application/pdf" and "Refund policy" in text


def test_docx_text() -> None:
    mime, text = extract_text("a.docx", _zip({"word/document.xml": _DOCX_XML.encode()}))
    assert mime.endswith("wordprocessingml.document") and text == "Hello world\nSecond"


def test_docx_zip_bomb_rejected() -> None:
    bomb = _zip({"word/document.xml": _DOCX_XML.encode(), "pad.bin": b"\0" * 5_000_000})
    with pytest.raises(ExtractionError) as exc:
        extract_text("a.docx", bomb)
    assert exc.value.code == "zip_bomb"


def test_encrypted_pdf_rejected() -> None:
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(ExtractionError) as exc:
        extract_text("a.pdf", buf.getvalue())
    assert exc.value.code == "encrypted_pdf"


def test_garbage_pdf_and_docx_rejected() -> None:
    for name in ("a.pdf", "a.docx", "a.json"):
        with pytest.raises(ExtractionError) as exc:
            extract_text(name, b"\x00\x01 not really")
        assert exc.value.code == "extraction_failed"


def test_unknown_extension_rejected() -> None:
    for name in ("a.exe", "noext"):
        with pytest.raises(ExtractionError) as exc:
            extract_text(name, b"MZ")
        assert exc.value.code == "unsupported_document"


def test_hindi_text_roundtrips_nfc() -> None:
    src = "नमस्ते दुनिया, ಕನ್ನಡ"
    _, text = extract_text("a.txt", unicodedata.normalize("NFD", src).encode())
    assert text == unicodedata.normalize("NFC", src)
