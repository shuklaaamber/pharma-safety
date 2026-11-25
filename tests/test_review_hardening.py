"""Regression tests for findings 2, 3, 4, 5 and 7 of docs/review-evidence.md."""
import sqlite3
from datetime import date

import httpx
import pytest

from pharma_intake import audit
from pharma_intake import workflow as wf
from pharma_intake.agent.orchestrator import AgentOrchestrator
from pharma_intake.agent.router import Route, route
from pharma_intake.db import Database
from pharma_intake.models import IntakeReport, ReporterType, ReportType
from pharma_intake.rag import generator as gen
from pharma_intake.rag.generator import LLMError, OpenRouterClient
from pharma_intake.rag.chunker import Chunk
from pharma_intake.rag.pipeline import HybridRetriever, ScoredChunk, load_sop_documents


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "h.db")


@pytest.fixture
def ref(db):
    return db.create_report(
        IntakeReport(
            report_type=ReportType.QUALITY_COMPLAINT,
            product_name="Examplomab",
            batch_lot="LOT-12345",
            date_received=date(2026, 11, 20),
            reporter_type=ReporterType.CONSUMER,
            description="Fictional.",
        )
    )


# ---------------------------------------------------------------- finding 4: scope
@pytest.mark.parametrize(
    "text",
    [
        "Is the rash a side effect of Examplomab?",
        "Could Examplomab be responsible for the nausea?",
        "What is the deadline to submit to the FDA?",
        "Do we have to file this with EMA within 15 days",
        "Can I give ibuprofen for the headache?",
        "Is it safe to take this with alcohol?",
    ],
)
def test_router_refuses_scope_violations(text):
    assert route(text).route is Route.REFUSE


@pytest.mark.parametrize(
    "text",
    [
        "What does the SOP say about lot LOT-88392?",
        "How are product quality complaints triaged?",
        "What is the review period for new reports?",
        "Which SOP covers batch record checks?",
    ],
)
def test_router_still_answers_benign_questions(text):
    assert route(text).route is Route.RAG


@pytest.mark.parametrize(
    "text",
    [
        "Serious events are submitted to the FDA within 15 days [S1].",
        "The rash is a side effect of the product [S1].",
        "Take two tablets with food [S1].",
        "Notify the regulator within 7 days [S1].",
    ],
)
def test_grounding_rejects_scope_violations(text):
    assert gen.check_grounding(text, 1) == "answer contained out-of-scope language"


def test_grounding_accepts_plain_cited_sentence():
    assert gen.check_grounding("Complaints are triaged by the intake team [S1].", 1) is None


# ------------------------------------------------- finding 2: DB-level HITL guard
def test_cannot_insert_approved_row_directly(db, ref):
    wf.request_status_change(db, ref, "In Review")
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError, match="open as Pending"):
        conn.execute(
            "INSERT INTO approvals (ref, requested_at, decision) VALUES (?, 'x', 'Approved')",
            (ref,),
        )
    conn.close()
    assert db.get_report(ref)["status"] == "In Review"


def test_cannot_open_approval_for_report_not_in_review(db, ref):
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError, match="open as Pending"):
        conn.execute(
            "INSERT INTO approvals (ref, requested_at, decision) VALUES (?, 'x', 'Pending')",
            (ref,),
        )
    conn.close()


def _pending_approval(db, ref):
    wf.request_status_change(db, ref, "In Review")
    wf.request_status_change(db, ref, "Closed")


@pytest.mark.parametrize(
    "set_clause",
    [
        "decision='Approved'",  # no reviewer / rationale / timestamp
        "decision='Approved', decided_at='t', reviewer_id='Jane Doe', rationale='ok'",
        "decision='Approved', decided_at='t', reviewer_id='REV-001', rationale='   '",
        "decision='Approved', reviewer_id='REV-001', rationale='ok'",  # no timestamp
    ],
)
def test_decision_requires_reviewer_rationale_and_timestamp(db, ref, set_clause):
    _pending_approval(db, ref)
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError, match="requires reviewer ID"):
        conn.execute(f"UPDATE approvals SET {set_clause} WHERE ref=?", (ref,))
    conn.close()
    assert db.get_report(ref)["status"] == "In Review"


def test_complete_decision_is_still_accepted_by_trigger(db, ref):
    _pending_approval(db, ref)
    res = wf.decide_closure(db, ref, "Approved", "REV-001", "QA Lead", "Checks complete")
    assert res.ok and db.get_report(ref)["status"] == "Closed"


def test_cannot_insert_report_that_is_already_closed(db):
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError, match="created as New"):
        conn.execute(
            "INSERT INTO reports (ref, report_type, product_name, batch_lot, date_received,"
            " reporter_type, description, status, created_at)"
            " VALUES ('REF-2026-9999','Product Quality Complaint','Examplomab','LOT-12345',"
            "'2026-11-20','Consumer','Fictional.','Closed','t')"
        )
    conn.close()


# ----------------------------------------------------------- finding 3: audit input
def test_audit_rejects_unknown_action_actor_and_ref(db):
    conn = db.connect()
    for kwargs in (
        {"action": "Jane Doe born 1980"},
        {"action": "LLM_CALL", "actor": "Jane Doe"},
        {"action": "LLM_CALL", "ref": "not a ref"},
    ):
        with pytest.raises(ValueError):
            audit.log_event(conn, **kwargs)
    conn.close()
    assert db.audit_events() == []


def make_agent(db):
    return AgentOrchestrator(db, lambda: HybridRetriever([]))


def test_breaker_trip_audits_only_a_generic_name_for_unknown_tools(db):
    agent = make_agent(db)
    hostile = "Jane Doe born 1980 headache"
    for _ in range(3):
        res = agent.call_tool(hostile, {"x": 1})
    assert res.code == "CIRCUIT_OPEN"
    rows = [r for r in db.audit_events() if r["action"] == "CIRCUIT_BREAKER_TRIPPED"]
    assert [r["detail"] for r in rows] == ["UNKNOWN_TOOL"]
    assert "Jane" not in " ".join(str(dict(r)) for r in db.audit_events())


def test_failed_trip_audit_cannot_mask_the_trip(db, monkeypatch):
    agent = make_agent(db)

    def boom(*a, **k):
        raise ValueError("audit rejected")

    monkeypatch.setattr(db, "log_audit", boom)
    for _ in range(3):
        res = agent.call_tool("nope", {})
    assert res.code == "CIRCUIT_OPEN" and "Audit write failed" in res.message
    assert agent.call_tool("rag_lookup", {"query": "x"}).code == "CIRCUIT_OPEN"  # still halted


# ------------------------------------------------- findings 5 and 7: LLM robustness
class FakeLLM:
    model = "fake/model"

    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def complete(self, system, user):
        self.calls += 1
        return self.reply


def one_chunk():
    chunk = Chunk(chunk_id="c1", doc_id="d1", source="SOP-001", text="Complaints are triaged by the intake team.")
    return [ScoredChunk(chunk=chunk, score=0.9)]


@pytest.mark.parametrize("reply", [None, 123, "", "   "])
def test_non_text_or_empty_llm_reply_falls_back_to_extractive(reply):
    a = gen.generate_answer("triage", one_chunk(), FakeLLM(reply), allow_external=True)
    assert a.mode == "extractive" and "LLM request failed" in a.reason


def client_with(handler):
    return OpenRouterClient("test-key", "fake/model", http=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize(
    "body",
    [
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": 5}}]},
        {"choices": None},
        {"choices": [None]},
        [],
    ],
)
def test_openrouter_client_raises_llmerror_on_odd_payloads(body):
    c = client_with(lambda req: httpx.Response(200, json=body))
    with pytest.raises(LLMError):
        c.complete("s", "u")


def test_openrouter_client_returns_text():
    c = client_with(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "Hi [S1]."}}]}))
    assert c.complete("s", "u") == "Hi [S1]."


def test_unauditable_outbound_call_is_blocked(monkeypatch):
    llm = FakeLLM("Complaints are triaged by the intake team [S1].")

    def boom(model, n):
        raise ValueError("bad model string")

    a = gen.generate_answer("triage", one_chunk(), llm, allow_external=True, on_external_call=boom)
    assert a.mode == "extractive" and "could not be audited" in a.reason
    assert llm.calls == 0 and a.external_call is False


def test_llm_call_audit_sanitises_model_name(db):
    class WeirdModel(FakeLLM):
        model = "Jane Doe!! <b>x</b> " + "m" * 100

    llm = WeirdModel("NOT_FOUND")
    agent = AgentOrchestrator(
        db, lambda: HybridRetriever(load_sop_documents()), llm, allow_external=True
    )
    res = agent.call_tool("rag_lookup", {"query": "who approves closure of a report?"})
    assert res.ok and llm.calls == 1  # the call was made, not aborted by the audit write
    rows = [r for r in db.audit_events() if r["action"] == "LLM_CALL"]
    assert len(rows) == 1
    model_part, _, count = rows[0]["detail"].partition(" chunks ")
    assert count == "1" and 0 < len(model_part) <= 40
    assert not set(model_part) & set("!<> ")  # disallowed characters stripped
