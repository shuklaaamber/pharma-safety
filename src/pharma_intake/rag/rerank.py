"""Stage 4: precision reranking of query-document pairs.

`Reranker.score` returns relevance in [0, 1]. The offline default
(`JointOverlapReranker`) scores each (query, chunk) pair jointly: IDF-weighted
coverage of query terms (synonym-aware) blended with adjacent-pair overlap.
`CrossEncoderReranker` is an optional drop-in (needs sentence-transformers).
"""
from __future__ import annotations

import math
from typing import Protocol

from .text import analyze, tokenize


class Reranker(Protocol):
    def score(self, query: str, texts: list[str]) -> list[float]: ...


class JointOverlapReranker:
    def __init__(self, corpus_texts: list[str]):
        n = max(len(corpus_texts), 1)
        df: dict[str, int] = {}
        for t in corpus_texts:
            for tok in set(analyze(t)):
                df[tok] = df.get(tok, 0) + 1
        self._n, self._df = n, df

    def _idf(self, tok: str) -> float:
        f = self._df.get(tok, 0)  # unseen query terms get the maximum weight
        return math.log(1 + (self._n - f + 0.5) / (f + 0.5))

    def score(self, query: str, texts: list[str]) -> list[float]:
        q = list(dict.fromkeys(analyze(query, query=True)))
        if not q:
            return [0.0] * len(texts)
        total = sum(self._idf(t) for t in q)
        q_pairs = list(zip(tokenize(query), tokenize(query)[1:]))
        out = []
        for text in texts:
            d = set(analyze(text))
            cov = sum(self._idf(t) for t in q if t in d) / total if total else 0.0
            if q_pairs:
                toks = tokenize(text)
                d_pairs = set(zip(toks, toks[1:]))
                bi = sum(p in d_pairs for p in q_pairs) / len(q_pairs)
                s = 0.8 * cov + 0.2 * bi
            else:
                s = cov
            out.append(max(0.0, min(1.0, s)))
        return out


class CrossEncoderReranker:
    """Optional: requires `pip install sentence-transformers` (not in requirements)."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        from sentence_transformers import CrossEncoder  # lazy import

        self.model = CrossEncoder(model_name)

    def score(self, query: str, texts: list[str]) -> list[float]:
        raw = self.model.predict([(query, t) for t in texts])
        return [1.0 / (1.0 + math.exp(-float(r))) for r in raw]
