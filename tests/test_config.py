import re

from pharma_intake import config


def test_status_lifecycle_order():
    assert config.STATUSES == ("New", "In Review", "Closed")


def test_report_types():
    assert set(config.REPORT_TYPES) == {
        "Suspected Adverse Event",
        "Product Quality Complaint",
    }


def test_lot_pattern():
    assert re.match(config.LOT_PATTERN, "LOT-88392")
    assert not re.match(config.LOT_PATTERN, "LOT-8839")


def test_rag_parameters_match_spec():
    assert 1.2 <= config.BM25_K1 <= 1.5
    assert config.BM25_B == 0.75
    assert (config.CHUNK_TOKENS, config.CHUNK_OVERLAP) == (512, 64)
    assert config.RETRIEVER_TOP_N == 50
    assert config.RRF_K == 60
    assert config.RERANK_THRESHOLD == 0.40
