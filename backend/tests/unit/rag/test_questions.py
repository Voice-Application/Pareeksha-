"""Quote location, passage sampling and CSV parsing for RAG questions (Task 8)."""

from __future__ import annotations

import random
import uuid

import pytest

from pareeksha.rag.questions import CsvError, locate_quote, parse_csv, sample_passages


def test_locate_exact() -> None:
    doc = "Refunds are issued within 7 days. Shipping is free."
    assert locate_quote(doc, "Shipping is free.") == (34, 51)


def test_locate_normalised_whitespace_maps_offsets() -> None:
    doc = "Intro.\nRefunds   are\nissued within 7 days.  Next."
    span = locate_quote(doc, "refunds are issued WITHIN 7 days.")
    assert span is not None
    assert doc[span[0] : span[1]] == "Refunds   are\nissued within 7 days."


def test_locate_missing_none() -> None:
    assert locate_quote("Refunds in 7 days", "refunds in 30 days") is None
    assert locate_quote("anything", "   ") is None


def test_sampling_is_seeded_and_spread_across_documents() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    docs = [(a, "a.txt", "alpha " * 600), (b, "b.txt", "beta " * 600)]
    first = sample_passages(docs, 4, random.Random(7))
    assert first == sample_passages(docs, 4, random.Random(7))
    assert {p.document_id for p in first[:2]} == {a, b}
    texts = {d[0]: d[2] for d in docs}
    for p in first:
        assert p.text == texts[p.document_id][p.start : p.end]
        assert p.text == p.text.strip() and len(p.text) <= 1200


def test_parse_csv_bom_and_columns() -> None:
    data = "﻿Question,Expected_Answer,source_document,source_quote,extra\nq,a,d.txt,x,1\n"
    assert parse_csv(data.encode("utf-8")) == [
        {"question": "q", "expected_answer": "a", "source_document": "d.txt", "source_quote": "x"}
    ]
    with pytest.raises(CsvError, match="source_quote"):
        parse_csv(b"question,expected_answer,source_document\n")
