"""Dense scoring, rank fusion and MMR. Pure numpy, float32."""

import numpy as np


def _unit(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float32)
    norm = np.linalg.norm(m, axis=-1, keepdims=True)
    out: np.ndarray = m / np.where(norm == 0, 1.0, norm)
    return out


def dense_scores(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    if len(matrix) == 0:
        return np.zeros(0, dtype=np.float32)
    out: np.ndarray = (_unit(matrix) @ _unit(query_vec)).astype(np.float32)
    return out


def top_k(scores: np.ndarray | list[float], k: int) -> list[tuple[int, float]]:
    arr = np.asarray(scores, dtype=np.float32)
    order = np.argsort(-arr, kind="stable")[: max(k, 0)]
    return [(int(i), float(arr[i])) for i in order]


def rrf(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))


def mmr(
    query_vec: np.ndarray, matrix: np.ndarray, candidates: list[int], k: int, lam: float
) -> list[int]:
    if not candidates:
        return []
    vecs = _unit(matrix[candidates])
    rel = vecs @ _unit(query_vec)
    sim = vecs @ vecs.T
    chosen: list[int] = []  # positions into candidates
    rest = list(range(len(candidates)))

    def gain(p: int) -> float:
        redundancy = max(sim[p][c] for c in chosen) if chosen else 0.0
        return float(lam * rel[p] - (1 - lam) * redundancy)

    while rest and len(chosen) < k:
        best = max(rest, key=gain)
        chosen.append(best)
        rest.remove(best)
    return [candidates[p] for p in chosen]
