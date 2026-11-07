"""In-process Okapi BM25.

ponytail: in-memory per index, move to tsvector/pgvector when a KB exceeds ~50k chunks
"""

import math
from collections import Counter


class BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.n = len(docs)
        self.lens = [len(d) for d in docs]
        self.avg = (sum(self.lens) / self.n) if self.n else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, d in enumerate(docs):
            for term, tf in Counter(d).items():
                self.postings.setdefault(term, []).append((i, tf))

    def scores(self, query_tokens: list[str]) -> list[float]:
        out = [0.0] * self.n
        for term in set(query_tokens):
            post = self.postings.get(term)
            if not post:
                continue
            idf = math.log(1 + (self.n - len(post) + 0.5) / (len(post) + 0.5))
            for i, tf in post:
                norm = 1 - self.b + self.b * (self.lens[i] / self.avg if self.avg else 0.0)
                out[i] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        return out
