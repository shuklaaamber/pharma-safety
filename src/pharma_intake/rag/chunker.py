"""Documents and 512-token / 64-overlap chunking."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import CHUNK_OVERLAP, CHUNK_TOKENS

_WORD_RE = re.compile(r"\S+")


@dataclass(frozen=True)
class Document:
    doc_id: str
    source: str  # human-readable label shown in citations
    text: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    source: str
    text: str


def chunk_document(
    doc: Document, size: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    if overlap >= size:
        raise ValueError("overlap must be smaller than chunk size")
    spans = [m.span() for m in _WORD_RE.finditer(doc.text)]
    if not spans:
        return []
    step = size - overlap
    chunks: list[Chunk] = []
    start = 0
    while True:
        window = spans[start : start + size]
        text = doc.text[window[0][0] : window[-1][1]]
        chunks.append(Chunk(f"{doc.doc_id}#{len(chunks)}", doc.doc_id, doc.source, text))
        if start + size >= len(spans):
            break
        start += step
    return chunks


def chunk_documents(
    docs: list[Document], size: int = CHUNK_TOKENS, overlap: int = CHUNK_OVERLAP
) -> list[Chunk]:
    return [c for d in docs for c in chunk_document(d, size, overlap)]
