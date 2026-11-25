from datetime import date

import httpx
import pytest

from pharma_intake import config
from pharma_intake.db import Database
from pharma_intake.models import AEExtension, IntakeReport, ReporterType, ReportType
from pharma_intake.rag import generator as gen
from pharma_intake.rag.chunker import Document
from pharma_intake.rag.pipeline import (
    HybridRetriever,
    load_report_documents,
    load_sop_documents,
)


class FakeLLM:
    model = "fake/model"

    def __init__(self, reply="", error=None):
        self.reply, self.error, self.calls = reply, error, []

    def complete(self, system, user):
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return self.reply


@pytest.fixture
def retriever(tmp_path):
    db = Database(tmp_path / "r.db")
    db.create_report(
        IntakeReport(
            report_type=ReportType.ADVERSE_EVENT,
            product_name="Examplomab",
            batch_lot="LOT-88392",
            date_received=date(2026, 11, 20),
            reporter_type=ReporterType.CONSUMER,
            description="Fictional report of anaphylaxis after use.",
            ae=AEExtension(event_description="Fictional difficulty breathing.", onset_date=date(2026, 11, 19)),
        )
    )
    db.create_report(
        IntakeReport(
            report_type=ReportType.QUALITY_COMPLAINT,
            product_name="Examplomab",
            batch_lot="LOT-11111",
            date_received=date(2026, 11, 21),
            reporter_type=ReporterType.PHARMACIST,
            description="Blister packaging was torn.",
        )
    )
    return HybridRetriever(load_sop_documents() + load_report_documents(db))


# ---------------- retrieval
def test_exact_lot_query_finds_matching_report(retriever):
    res = retriever.retrieve("LOT-88392")
    assert res.selected and res.selected[0].chunk.doc_id == "report:REF-" + str(date.today().year) + "-0001"
    assert all("LOT-11111" not in s.chunk.text for s in res.selected)


def test_synonym_query_hits_terminology_sop_and_report(retriever):
    res = retriever.retrieve("difficulty breathing")
    ids = {s.chunk.doc_id for s in res.selected}
    assert "sop:SOP-005-terminology-aids" in ids
    assert any(i.startswith("report:") for i in ids)


def test_process_question_finds_sop(retriever):
    res = retriever.retrieve("who approves closure of a report?")
    assert res.selected[0].chunk.doc_id == "sop:SOP-003-status-lifecycle-and-closure"


def test_irrelevant_query_selects_nothing_and_trace_recorded(retriever):
    res = retriever.retrieve("banana smoothie recipe")
    assert res.selected == []
    assert retriever.retrieve("   ").selected == []


def test_selection_limits_and_threshold(retriever):
    res = retriever.retrieve("report batch status")
    assert len(res.selected) <= config.CONTEXT_MAX_CHUNKS
    assert all(s.score >= config.RERANK_THRESHOLD for s in res.selected)
    assert res.reranked == sorted(res.reranked, key=lambda s: -s.score)
    assert len(res.bm25_ids) <= config.RETRIEVER_TOP_N


def test_empty_corpus():
    assert HybridRetriever([]).retrieve("anything").selected == []


def test_top_n_caps_candidates():
    docs = [Document(f"d{i}", f"D{i}", f"common term number {i}") for i in range(10)]
    res = HybridRetriever(docs, top_n=3).retrieve("common term")
    assert len(res.bm25_ids) == 3 and len(res.dense_ids) == 3


# ---------------- generation guardrails
def pick(retriever, q="LOT-88392"):
    return retriever.retrieve(q).selected


def test_no_source_skips_llm(retriever):
    llm = FakeLLM("should not be called")
    a = gen.generate_answer("banana smoothie recipe", [], llm, allow_external=True)
    assert a.mode == "no_source" and a.text == gen.NO_SOURCE_TEXT and llm.calls == []


def test_external_disabled_or_no_client_is_extractive(retriever):
    sel = pick(retriever)
    llm = FakeLLM("x [S1].")
    off = gen.generate_answer("LOT-88392", sel, llm, allow_external=False)
    assert off.mode == "extractive" and llm.calls == [] and "[S1]" in off.text
    nokey = gen.generate_answer("LOT-88392", sel, None, allow_external=True)
    assert nokey.mode == "extractive" and "key" in nokey.reason


def test_cited_answer_accepted_and_call_audited(retriever):
    sel = pick(retriever)
    calls = []
    llm = FakeLLM("Batch LOT-88392 appears in a stored report [S1].")
    a = gen.generate_answer("LOT-88392", sel, llm, allow_external=True,
                            on_external_call=lambda m, n: calls.append((m, n)))
    assert a.mode == "llm" and a.external_call and calls == [("fake/model", len(sel))]
    system, user = llm.calls[0]
    assert "NEVER assess causality" in system and "[S1]" in user


@pytest.mark.parametrize(
    "reply, why",
    [
        ("The batch appears in a stored report.", "uncited"),
        ("The batch appears in a stored report [S9].", "invalid"),
        ("The product caused the reaction in this case [S1].", "scope"),
        ("This event is reportable to the authority [S1].", "scope"),
        ("Recommended treatment is to rest at home [S1].", "scope"),
    ],
)
def test_bad_llm_output_falls_back_to_extractive(retriever, reply, why):
    a = gen.generate_answer("LOT-88392", pick(retriever), FakeLLM(reply), allow_external=True)
    assert a.mode == "extractive" and "rejected" in a.reason and a.external_call


def test_not_found_reply(retriever):
    a = gen.generate_answer("LOT-88392", pick(retriever), FakeLLM("NOT_FOUND"), allow_external=True)
    assert a.mode == "no_source"


def test_llm_error_falls_back(retriever):
    llm = FakeLLM(error=gen.LLMError("LLM request failed: ConnectError"))
    a = gen.generate_answer("LOT-88392", pick(retriever), llm, allow_external=True)
    assert a.mode == "extractive" and "failed" in a.reason


def test_pii_blocks_outbound_call(retriever):
    llm = FakeLLM("x [S1].")
    a = gen.generate_answer("email me at jane@example.com about LOT-88392",
                            pick(retriever), llm, allow_external=True)
    assert a.mode == "extractive" and llm.calls == [] and not a.external_call
    assert "personal data" in a.reason


# ---------------- OpenRouter client (mocked HTTP only)
def _client(handler):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return gen.OpenRouterClient("sk-test-123", "some/model", http=http)


def test_openrouter_request_shape_and_parse():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello [S1]."}}]})

    out = _client(handler).complete("sys", "usr")
    assert out == "hello [S1]."
    assert seen["url"] == config.OPENROUTER_URL and seen["auth"] == "Bearer sk-test-123"
    assert '"temperature":0' in seen["body"].replace(" ", "") and "some/model" in seen["body"]


@pytest.mark.parametrize(
    "response",
    [httpx.Response(500), httpx.Response(401), httpx.Response(200, json={"oops": 1}),
     httpx.Response(200, text="not json")],
)
def test_openrouter_errors_become_llmerror_without_leaking_key(response):
    with pytest.raises(gen.LLMError) as e:
        _client(lambda r: response).complete("s", "u")
    assert "sk-test" not in str(e.value)


def test_openrouter_network_error():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(gen.LLMError):
        _client(handler).complete("s", "u")


def test_default_client_needs_key(monkeypatch):
    assert gen.default_client() is None  # conftest strips the key
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_MODEL", "m/x")
    c = gen.default_client()
    assert c.model == "m/x"
