"""Stage 2: dense semantic retrieval (bi-encoder interface + offline default).

`LsaEncoder` (TF-IDF + truncated SVD, numpy only) is the offline default.
`SentenceTransformerEncoder` is an optional drop-in when that package is installed.
Both rank by cosine similarity over L2-normalised vectors.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Protocol

import numpy as np

from .text import analyze


class Encoder(Protocol):
    def fit(self, texts: list[str]) -> None: ...
    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray: ...


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return np.divide(m, norms, out=np.zeros_like(m), where=norms > 1e-12)


class LsaEncoder:
    def __init__(self, dims: int = 64):
        self.dims = dims
        self.vocab: dict[str, int] = {}
        self.idf: np.ndarray = np.zeros(0)
        self.components: np.ndarray = np.zeros((0, 0))

    def fit(self, texts: list[str]) -> None:
        analyzed = [analyze(t) for t in texts]
        terms = sorted({t for toks in analyzed for t in toks})
        self.vocab = {t: i for i, t in enumerate(terms)}
        n = max(len(texts), 1)
        df = np.zeros(len(terms))
        for toks in analyzed:
            for t in set(toks):
                df[self.vocab[t]] += 1
        self.idf = np.log(1 + (n - df + 0.5) / (df + 0.5)) if terms else np.zeros(0)
        x = self._tfidf(analyzed)
        if x.size == 0:
            self.components = np.zeros((0, len(terms)))
            return
        _, s, vt = np.linalg.svd(x, full_matrices=False)
        k = max(1, min(self.dims, int((s > 1e-10).sum())))
        self.components = vt[:k]

    def _tfidf(self, analyzed: list[list[str]]) -> np.ndarray:
        x = np.zeros((len(analyzed), len(self.vocab)))
        for r, toks in enumerate(analyzed):
            for t, c in Counter(toks).items():
                j = self.vocab.get(t)
                if j is not None:
                    x[r, j] = (1 + math.log(c)) * self.idf[j]
        return x

    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        x = self._tfidf([analyze(t, query=query) for t in texts])
        if self.components.shape[0] == 0:
            return np.zeros((len(texts), 1))
        return _normalize(x @ self.components.T)


class SentenceTransformerEncoder:
    """Optional: requires `pip install sentence-transformers` (not in requirements)."""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer  # lazy import

        self.model = SentenceTransformer(model_name)

    def fit(self, texts: list[str]) -> None:  # pretrained: nothing to fit
        return None

    def encode(self, texts: list[str], *, query: bool = False) -> np.ndarray:
        return np.asarray(self.model.encode(texts, normalize_embeddings=True))


class DenseIndex:
    def __init__(self, texts: list[str], encoder: Encoder):
        self.encoder = encoder
        encoder.fit(texts)
        self.matrix = encoder.encode(texts) if texts else np.zeros((0, 1))

    def search(self, query: str, top_n: int) -> list[tuple[int, float]]:
        if self.matrix.shape[0] == 0:
            return []
        q = self.encoder.encode([query], query=True)[0]
        sims = self.matrix @ q  # cosine: both sides are unit vectors
        order = sorted(range(len(sims)), key=lambda i: (-sims[i], i))
        return [(i, float(sims[i])) for i in order[:top_n] if sims[i] > 1e-9]
