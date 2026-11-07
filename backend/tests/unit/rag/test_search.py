import numpy as np

from pareeksha.rag.search import dense_scores, mmr, rrf, top_k


def test_dense_and_top_k() -> None:
    m = np.array([[1, 0], [0, 0], [3, 3]], dtype=np.float32)
    s = dense_scores(np.array([1, 0], dtype=np.float32), m)
    assert s.dtype == np.float32
    assert s[1] == 0.0
    assert [i for i, _ in top_k(s, 2)] == [0, 2]


def test_rrf_fuses() -> None:
    fused = rrf([[1, 2, 3], [3, 1, 4]])
    assert [i for i, _ in fused][:2] == [1, 3]
    assert abs(dict(fused)[1] - (1 / 61 + 1 / 62)) < 1e-9


def test_mmr_diversifies() -> None:
    m = np.array([[1, 0], [1, 0], [0.6, 0.8]], dtype=np.float32)
    q = np.array([1, 0], dtype=np.float32)
    assert mmr(q, m, [0, 1, 2], 2, 0.3) == [0, 2]
    assert mmr(q, m, [], 2, 0.3) == []
