"""Stage 1: lexical sparse retrieval (BM25, own implementation)."""
from __future__ import annotations

import math
from collections import Counter

from ..config import BM25_B, BM25_K1
from .text import tokenize


class BM25Index:
    def __init__(self, texts: list[str], k1: float = BM25_K1, b: float = BM25_B):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(t)) for t in texts]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.n = len(texts)
        self.avgdl = (sum(self.lengths) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d.keys())
        self.idf = {
            t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()
        }

    def score(self, query_tokens: list[str], i: int) -> float:
        doc, dl = self.docs[i], self.lengths[i]
        s = 0.0
        for t in set(query_tokens):
            tf = doc.get(t, 0)
            if not tf:
                continue
            denom = tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1.0))
            s += self.idf[t] * tf * (self.k1 + 1) / denom
        return s

    def search(self, query: str, top_n: int) -> list[tuple[int, float]]:
        q = tokenize(query)
        scored = [(i, self.score(q, i)) for i in range(self.n)]
        scored = [x for x in scored if x[1] > 0]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:top_n]
