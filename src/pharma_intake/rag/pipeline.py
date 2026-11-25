"""Four-stage hybrid retrieval: BM25 + bi-encoder -> RRF -> rerank + threshold."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .. import config
from ..db import Database
from .bm25 import BM25Index
from .chunker import Chunk, Document, chunk_documents
from .dense import DenseIndex, Encoder, LsaEncoder
from .rerank import JointOverlapReranker, Reranker
from .rrf import rrf_fuse


@dataclass(frozen=True)
class ScoredChunk:
    chunk: Chunk
    score: float


@dataclass
class RetrievalResult:
    query: str
    bm25_ids: list[str] = field(default_factory=list)
    dense_ids: list[str] = field(default_factory=list)
    fused_ids: list[str] = field(default_factory=list)
    reranked: list[ScoredChunk] = field(default_factory=list)  # all fused, scored
    selected: list[ScoredChunk] = field(default_factory=list)  # >= threshold, top-k


def load_sop_documents(sop_dir: Path = config.SOP_DIR) -> list[Document]:
    docs = []
    for p in sorted(Path(sop_dir).glob("*.md")):
        docs.append(Document(f"sop:{p.stem}", f"SOP {p.stem}", p.read_text(encoding="utf-8")))
    return docs


def load_report_documents(db: Database) -> list[Document]:
    """Saved (synthetic) reports as searchable documents."""
    docs = []
    for r in db.list_reports():
        parts = [
            f"Report {r['ref']}", r["report_type"], f"Product {r['product_name']}",
            f"Batch {r['batch_lot']}", f"Status {r['status']}", r["description"],
        ]
        if r["event_description"]:
            parts.append(f"Event: {r['event_description']}")
        docs.append(Document(f"report:{r['ref']}", f"Report {r['ref']}", ". ".join(parts)))
    return docs


class HybridRetriever:
    def __init__(
        self,
        documents: list[Document],
        encoder: Optional[Encoder] = None,
        reranker: Optional[Reranker] = None,
        *,
        chunk_size: int = config.CHUNK_TOKENS,
        overlap: int = config.CHUNK_OVERLAP,
        top_n: int = config.RETRIEVER_TOP_N,
        threshold: float = config.RERANK_THRESHOLD,
        max_context: int = config.CONTEXT_MAX_CHUNKS,
    ):
        self.chunks = chunk_documents(documents, chunk_size, overlap)
        texts = [c.text for c in self.chunks]
        self.bm25 = BM25Index(texts)
        self.dense = DenseIndex(texts, encoder or LsaEncoder())
        self.reranker = reranker or JointOverlapReranker(texts)
        self.top_n, self.threshold, self.max_context = top_n, threshold, max_context

    def retrieve(self, query: str) -> RetrievalResult:
        res = RetrievalResult(query=query)
        if not self.chunks or not query.strip():
            return res
        sparse = [i for i, _ in self.bm25.search(query, self.top_n)]
        dense = [i for i, _ in self.dense.search(query, self.top_n)]
        fused = [i for i, _ in rrf_fuse([sparse, dense])]
        cid = lambda idx: [self.chunks[i].chunk_id for i in idx]  # noqa: E731
        res.bm25_ids, res.dense_ids, res.fused_ids = cid(sparse), cid(dense), cid(fused)
        if not fused:
            return res
        scores = self.reranker.score(query, [self.chunks[i].text for i in fused])
        res.reranked = sorted(
            (ScoredChunk(self.chunks[i], s) for i, s in zip(fused, scores)),
            key=lambda sc: -sc.score,
        )
        res.selected = [sc for sc in res.reranked if sc.score >= self.threshold][
            : self.max_context
        ]
        return res
