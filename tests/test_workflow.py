import sqlite3
from datetime import date

import pytest

from pharma_intake import workflow as wf
from pharma_intake.db import Database
from pharma_intake.models import IntakeReport, ReporterType, ReportType

RATIONALE = "UNIQUE-RATIONALE-MARKER review complete"


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "w.db")


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


def status(db, ref):
    return db.get_report(ref)["status"]


def approve(db, ref, decision="Approved", rid="REV-001", role="QA Lead", why=RATIONALE):
    return wf.decide_closure(db, ref, decision, rid, role, why)


def to_review(db, ref):
    assert wf.request_status_change(db, ref, "In Review").ok


def test_new_to_in_review(db, ref):
    r = wf.request_status_change(db, ref, "In Review")
    assert r.ok and status(db, ref) == "In Review"


@pytest.mark.parametrize("target", ["Closed", "New", "Bogus"])
def test_illegal_from_new(db, ref, target):
    r = wf.request_status_change(db, ref, target)
    assert not r.ok and status(db, ref) == "New"


def test_skip_message_is_explicit(db, ref):
    assert "In Review before" in wf.request_status_change(db, ref, "Closed").message


def test_cannot_go_backwards(db, ref):
    to_review(db, ref)
    assert not wf.request_status_change(db, ref, "New").ok
    assert not wf.request_status_change(db, ref, "In Review").ok


def test_closure_request_freezes_state_until_approval(db, ref):
    to_review(db, ref)
    r = wf.request_status_change(db, ref, "Closed")
    assert r.ok and r.pending_approval and status(db, ref) == "In Review"
    assert wf.pending_approval(db, ref) and wf.pending_refs(db) == [ref]
    dup = wf.request_status_change(db, ref, "Closed")
    assert not dup.ok and dup.pending_approval


def test_approval_closes_and_is_audited(db, ref):
    to_review(db, ref)
    wf.request_status_change(db, ref, "Closed")
    r = approve(db, ref)
    assert r.ok and status(db, ref) == "Closed"
    events = db.audit_events(ref)
    assert [e["action"] for e in events] == [
        "REPORT_CREATED",
        "STATUS_CHANGED",
        "CLOSURE_REQUESTED",
        "CLOSURE_APPROVED",
    ]
    assert events[-1]["actor"] == "REV-001"
    assert RATIONALE not in " ".join(str(tuple(e)) for e in db.audit_events())
    assert not wf.request_status_change(db, ref, "In Review").ok  # Closed is final


def test_rejection_keeps_in_review_and_allows_new_request(db, ref):
    to_review(db, ref)
    wf.request_status_change(db, ref, "Closed")
    r = approve(db, ref, decision="Rejected")
    assert r.ok and status(db, ref) == "In Review" and not wf.pending_approval(db, ref)
    assert wf.request_status_change(db, ref, "Closed").ok


def test_decision_without_pending_request_fails(db, ref):
    to_review(db, ref)
    assert not approve(db, ref).ok
    assert status(db, ref) == "In Review"


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(rid="Jane Doe"),
        dict(rid=""),
        dict(role="Intern"),
        dict(why=""),
        dict(why="x" * 201),
        dict(why="contact me at a@b.com"),
        dict(decision="Maybe"),
    ],
)
def test_invalid_reviewer_input_rejected_and_state_frozen(db, ref, kwargs):
    to_review(db, ref)
    wf.request_status_change(db, ref, "Closed")
    assert not approve(db, ref, **kwargs).ok
    assert status(db, ref) == "In Review" and wf.pending_approval(db, ref)


def test_db_trigger_blocks_direct_close_without_approval(db, ref):
    to_review(db, ref)
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError, match="illegal status transition"):
        conn.execute("UPDATE reports SET status='Closed' WHERE ref=?", (ref,))
    conn.close()


def test_db_trigger_blocks_skipping_new_to_closed(db, ref):
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError, match="illegal status transition"):
        conn.execute("UPDATE reports SET status='Closed' WHERE ref=?", (ref,))
    conn.close()


def test_approval_decision_is_final(db, ref):
    to_review(db, ref)
    wf.request_status_change(db, ref, "Closed")
    approve(db, ref, decision="Rejected")
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError, match="final"):
        conn.execute("UPDATE approvals SET decision='Approved'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM approvals")
    conn.close()


def test_unknown_ref(db):
    assert not wf.request_status_change(db, "REF-2026-9999", "In Review").ok
    assert not approve(db, "REF-2026-9999").ok
