from pareeksha.rag.bm25 import BM25
from pareeksha.rag.chunking import tokenize


def test_bm25_ranks_exact_term_first() -> None:
    docs = [
        "home loan interest rate",
        "किसान क्रेडिट कार्ड पर ब्याज",
        "gold loan tenure and fees",
    ]
    bm = BM25([tokenize(d) for d in docs])
    s = bm.scores(tokenize("क्रेडिट"))
    assert s.index(max(s)) == 1
    assert s[0] == 0.0
    s = bm.scores(tokenize("gold loan"))
    assert s.index(max(s)) == 2


def test_bm25_empty() -> None:
    assert BM25([]).scores(["a"]) == []
    assert BM25([["a"]]).scores(["zzz"]) == [0.0]
