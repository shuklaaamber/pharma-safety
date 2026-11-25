from datetime import date

import pytest

from pharma_intake.agent.circuit_breaker import CircuitBreaker, call_signature
from pharma_intake.agent.tools import SCHEMAS, ToolRuntime, repair_args
from pharma_intake.db import Database
from pharma_intake.rag.pipeline import HybridRetriever

GOOD = {
    "report_type": "Product Quality Complaint",
    "product_name": "Examplomab",
    "batch_lot": "LOT-12345",
    "date_received": "2026-11-20",
    "reporter_type": "Consumer",
    "description": "Blister packaging was torn.",
}


@pytest.fixture
def rt(tmp_path):
    db = Database(tmp_path / "a.db")
    return ToolRuntime(db, lambda: HybridRetriever([]))


def test_valid_submit_saves(rt):
    r = rt.execute("submit_intake_report", GOOD)
    assert r.ok and r.data["ref"].startswith("REF-") and r.data["status"] == "New"
    assert rt.db.get_report(r.data["ref"])["batch_lot"] == "LOT-12345"


@pytest.mark.parametrize("lot", ["LOT-1234", "ABC", "LOT-123456", ""])
def test_regex_batch_id_enforced(rt, lot):
    r = rt.execute("submit_intake_report", {**GOOD, "batch_lot": lot})
    assert not r.ok and r.code == "VALIDATION_ERROR" and r.invalid_args
    assert any(i["field"] == "batch_lot" for i in r.issues)


def test_missing_and_extra_fields(rt):
    bad = {k: v for k, v in GOOD.items() if k != "product_name"}
    r = rt.execute("submit_intake_report", {**bad, "patient_name": "x"})
    fields = {i["field"] for i in r.issues}
    assert {"product_name", "patient_name"} <= fields  # unknown field rejected, not ignored


def test_auto_repair_aliases_case_and_typos(rt):
    messy = {
        "Batch_ID": " lot-12345 ", "product": "Examplomab", "Report Type": "pqc",
        "date_recieved": "2026-11-20", "reporter_type": "consumer",
        "descripton": "Blister packaging was torn.",
    }
    r = rt.execute("submit_intake_report", messy)
    assert r.ok, r.message
    assert any("Batch_ID -> batch_lot" in n for n in r.repairs)
    assert any("date_recieved -> date_received" in n for n in r.repairs)
    assert rt.db.get_report(r.data["ref"])["batch_lot"] == "LOT-12345"


def test_repair_never_overwrites_duplicate_key():
    fixed, _ = repair_args("rag_lookup", {"query": "first", "q": "second"})
    assert fixed == {"query": "first"}


def test_domain_validation_pii_and_dates(rt):
    r = rt.execute("submit_intake_report", {**GOOD, "description": "call 555-123-4567 now"})
    assert r.code == "DOMAIN_VALIDATION" and r.invalid_args
    r = rt.execute("submit_intake_report", {**GOOD, "date_received": "2999-01-01"})
    assert r.code == "DOMAIN_VALIDATION"
    r = rt.execute("submit_intake_report", {**GOOD, "date_received": "not-a-date"})
    assert r.code == "VALIDATION_ERROR"


def test_ae_requires_event_fields(rt):
    ae = {**GOOD, "report_type": "ae"}
    assert rt.execute("submit_intake_report", ae).code == "DOMAIN_VALIDATION"
    ok = {**ae, "event_description": "Fictional event.", "onset_date": "2026-11-18"}
    assert rt.execute("submit_intake_report", ok).ok


def test_update_status_flow_and_hitl(rt):
    ref = rt.execute("submit_intake_report", GOOD).data["ref"]
    assert rt.execute("update_status", {"ref": ref.lower(), "status": "review"}).ok
    r = rt.execute("update_status", {"ref": ref, "target_status": "closed"})
    assert r.ok and r.data["pending_approval"] and r.data["status"] == "In Review"
    assert rt.db.get_report(ref)["status"] == "In Review"  # tool cannot close it


def test_no_tool_can_approve_closure():
    assert not any("approv" in name or "decide" in name for name in SCHEMAS)


def test_update_status_business_rejection_is_not_invalid_args(rt):
    ref = rt.execute("submit_intake_report", GOOD).data["ref"]
    r = rt.execute("update_status", {"ref": ref, "target_status": "Closed"})
    assert not r.ok and r.code == "WORKFLOW_REJECTED" and not r.invalid_args
    r = rt.execute("update_status", {"ref": "REF-bad", "target_status": "Closed"})
    assert r.code == "VALIDATION_ERROR"


def test_unknown_tool_and_non_dict(rt):
    assert rt.execute("drop_tables", {}).code == "UNKNOWN_TOOL"
    assert rt.execute("rag_lookup", ["x"]).code == "VALIDATION_ERROR"


# ---- circuit breaker (unit)
def test_breaker_trips_on_third_identical_invalid():
    cb, sig = CircuitBreaker(2), call_signature("t", {"a": 1})
    assert [cb.record(sig, True) for _ in range(3)] == [False, False, True]
    assert cb.tripped


def test_breaker_resets_on_valid_or_different_call():
    cb = CircuitBreaker(2)
    a, b = call_signature("t", {"a": 1}), call_signature("t", {"a": 2})
    cb.record(a, True); cb.record(a, True)
    cb.record(a, False)  # valid call resets
    cb.record(a, True); cb.record(a, True)
    assert not cb.tripped
    cb.record(b, True)  # different signature restarts the count
    cb.record(a, True)
    assert not cb.tripped and cb.consecutive_invalid == 1


def test_signature_is_order_independent_and_arg_sensitive():
    assert call_signature("t", {"a": 1, "b": 2}) == call_signature("t", {"b": 2, "a": 1})
    assert call_signature("t", {"a": 1}) != call_signature("u", {"a": 1})
    assert call_signature("t", {"a": 1}) != call_signature("t", {"a": 2})
