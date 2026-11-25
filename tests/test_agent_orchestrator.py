from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from pharma_intake import config
from pharma_intake.agent.orchestrator import AgentOrchestrator
from pharma_intake.agent.router import Route, extract_ref, extract_target_status, parse_fields, route
from pharma_intake.db import Database
from pharma_intake.rag.pipeline import HybridRetriever, load_report_documents, load_sop_documents

APP = str(Path(__file__).resolve().parents[1] / "app.py")
SUBMIT = ("submit report: report_type=Product Quality Complaint; product_name=Examplomab; "
          "batch_lot=LOT-12345; date_received=2026-11-20; reporter_type=Consumer; "
          "description=Blister packaging was torn")


@pytest.fixture
def agent(tmp_path):
    db = Database(tmp_path / "o.db")
    return AgentOrchestrator(
        db, lambda: HybridRetriever(load_sop_documents() + load_report_documents(db))
    )


# ---- router
@pytest.mark.parametrize(
    "text, expected",
    [
        ("hello", Route.DIRECT),
        ("Thanks!", Route.DIRECT),
        ("who approves closure of a report?", Route.RAG),
        ("LOT-88392 anaphylaxis", Route.RAG),
        ("difficulty breathing", Route.RAG),
        ("banana smoothie recipe", Route.RAG),
        ("move REF-2026-0001 to in review", Route.STATUS),
        ("what is the status of ref-2026-0001", Route.STATUS),
        ("submit report", Route.INTAKE),
        ("I want to log a new complaint", Route.INTAKE),
        ("did the drug cause the rash?", Route.REFUSE),
        ("is this event related to the product?", Route.REFUSE),
        ("what treatment should the patient take", Route.REFUSE),
        ("is this reportable to the FDA?", Route.REFUSE),
        ("do we need to report this to the authorities", Route.REFUSE),
    ],
)
def test_router(text, expected):
    assert route(text).route is expected


def test_refusal_beats_other_routes():
    assert route("submit report: did the drug cause it").route is Route.REFUSE


def test_router_helpers():
    assert extract_ref("close ref-2026-0007 please") == "REF-2026-0007"
    assert extract_target_status("please close it") == "Closed"
    assert extract_target_status("move to in review") == "In Review"
    assert extract_target_status("status of it") is None
    assert parse_fields("submit: a=1; b = two words\nc=3") == {"a": "1", "b": "two words", "c": "3"}


# ---- orchestrator
def test_direct_and_refusal_make_no_tool_calls(agent):
    assert "Hello" in agent.handle("hi").text
    r = agent.handle("did the drug cause the rash?")
    assert r.route is Route.REFUSE and "can't help" in r.text
    assert agent.db.audit_events() == []


def test_rag_route_cited_answer_and_no_source(agent):
    r = agent.handle("who approves closure of a report?")
    assert r.route is Route.RAG and "[S1]" in r.text
    assert agent.handle("banana smoothie recipe").text == "No sufficiently relevant source found."


def test_intake_template_then_submit_with_autorepair(agent):
    assert "key=value" in agent.handle("submit report").text
    r = agent.handle(SUBMIT.replace("batch_lot", "Batch_ID").replace("LOT-", "lot-"))
    assert r.tool_result.ok and "REF-" in r.text
    assert len(agent.db.list_reports()) == 1


def test_status_flow_hitl_pending(agent):
    ref = agent.handle(SUBMIT).tool_result.data["ref"]
    assert "In Review" in agent.handle(f"move {ref} to in review").text
    r = agent.handle(f"close {ref}")
    assert r.pending_approval and r.text.startswith("PENDING_APPROVAL")
    assert agent.db.get_report(ref)["status"] == "In Review"
    assert "awaiting human approval" in agent.handle(f"what is the status of {ref}").text
    assert "not found" in agent.handle("status of REF-2026-9999").text


def test_circuit_breaker_halts_after_three_identical_invalid_calls(agent):
    bad = {"query": "x"}  # min_length=2 -> invalid
    r1, r2, r3 = (agent.call_tool("rag_lookup", bad) for _ in range(3))
    assert (r1.code, r2.code) == ("VALIDATION_ERROR", "VALIDATION_ERROR")
    assert r3.code == "CIRCUIT_OPEN" and agent.breaker.tripped
    assert [e["action"] for e in agent.db.audit_events()] == ["CIRCUIT_BREAKER_TRIPPED"]
    # everything is halted now, even a valid call, until reset
    assert agent.call_tool("rag_lookup", {"query": "closure"}).code == "CIRCUIT_OPEN"
    assert agent.handle("who approves closure?").halted
    agent.reset_breaker()
    assert agent.call_tool("rag_lookup", {"query": "closure"}).ok


def test_breaker_not_tripped_by_alternating_or_business_failures(agent):
    for _ in range(5):
        agent.call_tool("rag_lookup", {"query": "x"})
        agent.call_tool("rag_lookup", {"query": "y"})  # different signature each time
    assert not agent.breaker.tripped
    ref = agent.handle(SUBMIT).tool_result.data["ref"]
    for _ in range(5):  # valid args, rejected by workflow: not "invalid arguments"
        agent.call_tool("update_status", {"ref": ref, "target_status": "Closed"})
    assert not agent.breaker.tripped


def test_breaker_via_chat_messages(agent):
    bad = "submit report: product_name=Examplomab; batch_lot=LOT-1"
    outs = [agent.handle(bad) for _ in range(3)]
    assert [o.halted for o in outs] == [False, False, True]
    assert "batch_lot" in outs[0].text


def test_short_term_memory_trace_is_bounded_and_volatile(agent):
    for _ in range(60):
        agent.handle("hi")
    assert len(agent.short_term.steps) == 50
    assert agent.long_term.report_state("REF-2026-0001") is None


# ---- UI
def test_ui_chat_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "ui.db")
    at = AppTest.from_file(APP).run(timeout=30)
    box = [t for t in at.text_input if t.label.startswith("Ask about")][0]
    box.set_value("did the drug cause the rash?")
    at.button(key="btn_ask").click().run(timeout=30)
    assert not at.exception and any("can't help" in m.value.replace(chr(92), "") for m in at.markdown)
    assert any("out_of_scope" in c.value for c in at.caption)
