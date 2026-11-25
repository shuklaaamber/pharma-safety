import math

import pytest

from pharma_intake.rag.bm25 import BM25Index
from pharma_intake.rag.chunker import Document, chunk_document
from pharma_intake.rag.dense import DenseIndex, LsaEncoder
from pharma_intake.rag.rerank import JointOverlapReranker
from pharma_intake.rag.rrf import rrf_fuse
from pharma_intake.rag.text import analyze, tokenize

TEXTS = [
    "Report REF-2026-0001 batch LOT-88392 anaphylaxis reported after dose.",
    "Report REF-2026-0002 batch LOT-11111 blister packaging torn.",
    "SOP terminology: dyspnea is also described as shortness of breath.",
    "Closure requires human compliance approval by a reviewer.",
    "A long unrelated document " + "filler " * 200 + "LOT-88392",
]


# ---- tokenizer / lexicon
def test_tokenizer_keeps_identifiers_whole():
    assert "lot-88392" in tokenize("Lot LOT-88392, REF-2026-0001!")
    assert "ref-2026-0001" in tokenize("see REF-2026-0001")


def test_query_phrase_replaced_by_concept():
    toks = analyze("difficulty breathing", query=True)
    assert toks == ["c_respiratory_distress"]
    assert "c_respiratory_distress" in analyze("patient reported dyspnea")


# ---- chunker
def test_chunk_size_and_overlap():
    doc = Document("d", "D", " ".join(f"w{i}" for i in range(25)))
    chunks = chunk_document(doc, size=10, overlap=4)
    words = [c.text.split() for c in chunks]
    assert [len(w) for w in words] == [10, 10, 10, 7]
    assert words[0][-4:] == words[1][:4]  # 4-token overlap
    assert words[-1][-1] == "w24"
    assert [c.chunk_id for c in chunks][:2] == ["d#0", "d#1"]


def test_short_doc_single_chunk_and_empty_doc():
    assert len(chunk_document(Document("d", "D", "a b c"))) == 1
    assert chunk_document(Document("d", "D", "   ")) == []


def test_bad_overlap_rejected():
    with pytest.raises(ValueError):
        chunk_document(Document("d", "D", "a b"), size=4, overlap=4)


# ---- BM25
def test_bm25_exact_lot_match_ranks_first():
    idx = BM25Index(TEXTS)
    top = idx.search("LOT-88392", 5)
    assert top[0][0] == 0  # short doc beats the long diluted doc (length norm)
    assert {i for i, _ in top} == {0, 4}


def test_bm25_length_normalisation_effect():
    short = BM25Index(TEXTS, b=0.75).search("LOT-88392", 5)
    flat = BM25Index(TEXTS, b=0.0).search("LOT-88392", 5)
    gap_norm = dict(short)[0] - dict(short)[4]
    gap_flat = dict(flat)[0] - dict(flat)[4]
    assert gap_norm > gap_flat


def test_bm25_formula_single_term():
    idx = BM25Index(["alpha beta", "beta gamma", "gamma"], k1=1.2, b=0.75)
    n, df = 3, 1
    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    avgdl = (2 + 2 + 1) / 3
    expected = idf * 1 * 2.2 / (1 + 1.2 * (0.25 + 0.75 * 2 / avgdl))
    assert idx.score(["alpha"], 0) == pytest.approx(expected)


def test_bm25_no_match_and_empty():
    assert BM25Index(TEXTS).search("zzzz", 5) == []
    assert BM25Index([]).search("x", 5) == []


# ---- dense
def test_dense_matches_synonym_without_shared_words():
    idx = DenseIndex(TEXTS, LsaEncoder())
    top = idx.search("difficulty breathing", 3)
    assert top and top[0][0] == 2  # the 'dyspnea' / 'shortness of breath' doc


def test_dense_cosine_bounds_and_empty():
    idx = DenseIndex(TEXTS, LsaEncoder())
    assert all(-1.0001 <= s <= 1.0001 for _, s in idx.search("blister packaging", 5))
    assert DenseIndex([], LsaEncoder()).search("x", 5) == []
    assert idx.search("qqqq zzzz", 5) == []


# ---- RRF
def test_rrf_formula_and_order():
    fused = dict(rrf_fuse([[1, 2, 3], [3, 1, 4]], k=60))
    assert fused[1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[3] == pytest.approx(1 / 63 + 1 / 61)
    assert fused[4] == pytest.approx(1 / 63)
    assert [d for d, _ in rrf_fuse([[1, 2, 3], [3, 1, 4]])] == [1, 3, 2, 4]


def test_rrf_empty():
    assert rrf_fuse([[], []]) == []


# ---- reranker
def test_reranker_scores_in_range_and_ordering():
    rr = JointOverlapReranker(TEXTS)
    scores = rr.score("LOT-88392 anaphylaxis", TEXTS)
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[0] > 0.9 and scores[0] == max(scores)


def test_reranker_synonym_and_irrelevant():
    rr = JointOverlapReranker(TEXTS)
    assert rr.score("difficulty breathing", [TEXTS[2]])[0] >= 0.4
    assert rr.score("banana smoothie recipe", TEXTS) == [0.0] * len(TEXTS)
    assert rr.score("", TEXTS) == [0.0] * len(TEXTS)
