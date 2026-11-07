from itertools import pairwise
from typing import Literal

from pareeksha.rag.chunking import Chunk, chunk_document, tokenize
from pareeksha.schemas.rag import ChunkingConfig

DOC = (
    "# Loans\n\nA home loan has a fixed rate. The tenure is up to 30 years! Is it cheap? Yes.\n\n"
    "## ಕನ್ನಡ\n\nಇದು ಕನ್ನಡ ವಾಕ್ಯ. ಇದು ಇನ್ನೊಂದು ವಾಕ್ಯ. ಬಡ್ಡಿ ದರ ಕಡಿಮೆ ಇದೆ.\n\n"
    "## हिंदी\n\nकिसान क्रेडिट कार्ड पर ब्याज कम है। यह योजना सभी किसानों के लिए है॥ आवेदन करें।\n"
    "अगली पंक्ति में और जानकारी।\n\n" + "word " * 120 + "\n\n" + "x" * 300 + "\n"
)
STRATEGIES: tuple[Literal["fixed", "recursive", "sentence_window"], ...] = (
    "fixed",
    "recursive",
    "sentence_window",
)


def _check(doc: str, chunks: list[Chunk]) -> None:
    assert chunks
    for c in chunks:
        assert c.text
        assert c.text == doc[c.start : c.end]
        assert c.text == c.text.strip()
        assert 0 <= c.parent_start <= c.start < c.end <= c.parent_end <= len(doc)


def test_chunks_reconstruct_offsets() -> None:
    for strategy in STRATEGIES:
        for size in (100, 150, 400, 800):
            for overlap in (0, 20, size // 2):
                for window in (1, 3):
                    cfg = ChunkingConfig(
                        strategy=strategy, size=size, overlap=overlap, window=window
                    )
                    _check(DOC, chunk_document(DOC, cfg))


def test_no_headings_and_blank_documents() -> None:
    doc = "no headings. just text.\n\nsecond para"
    for strategy in STRATEGIES:
        _check(doc, chunk_document(doc, ChunkingConfig(strategy=strategy)))
        assert chunk_document("  \n\n ", ChunkingConfig(strategy=strategy)) == []
        assert chunk_document("", ChunkingConfig(strategy=strategy)) == []


def test_overlap_respected() -> None:
    doc = " ".join(f"w{i:03d}" for i in range(400))
    for strategy in ("fixed", "recursive"):
        chunks = chunk_document(doc, ChunkingConfig(strategy=strategy, size=200, overlap=50))
        assert len(chunks) > 3
        for a, b in pairwise(chunks):
            assert b.start < a.end
            assert a.end - b.start <= 50
            assert b.end - b.start <= 200


def test_recursive_prefers_headings() -> None:
    doc = "# One\n\nalpha beta.\n\n# Two\n\ngamma delta.\n"
    chunks = chunk_document(doc, ChunkingConfig(strategy="recursive", size=800, overlap=0))
    assert [c.text for c in chunks] == ["# One\n\nalpha beta.", "# Two\n\ngamma delta."]
    assert chunks[0].parent_end <= chunks[1].parent_start


def test_sentence_window_parent_span() -> None:
    doc = "One a. Two b. Three c. Four d. Five e."
    chunks = chunk_document(doc, ChunkingConfig(strategy="sentence_window", window=1))
    assert [c.text for c in chunks] == ["One a.", "Two b.", "Three c.", "Four d.", "Five e."]
    assert doc[chunks[0].parent_start : chunks[0].parent_end] == "One a. Two b."
    assert doc[chunks[2].parent_start : chunks[2].parent_end] == "Two b. Three c. Four d."
    assert doc[chunks[4].parent_start : chunks[4].parent_end] == "Four d. Five e."


def test_danda_splits_hindi_sentences() -> None:
    doc = "यह पहला वाक्य है। यह दूसरा है॥ तीसरा यहाँ।\nचौथा।"
    chunks = chunk_document(doc, ChunkingConfig(strategy="sentence_window"))
    assert [c.text for c in chunks] == [
        "यह पहला वाक्य है।",
        "यह दूसरा है॥",
        "तीसरा यहाँ।",
        "चौथा।",
    ]


def test_tokenize_keeps_devanagari_matras() -> None:
    assert tokenize("किसान क्रेडिट") == ["किसान", "क्रेडिट"]
    assert tokenize("Hello, World! ब्याज-दर। ok") == ["hello", "world", "ब्याज", "दर", "ok"]
