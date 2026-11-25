import sqlite3
from datetime import date

import pytest

from pharma_intake import audit
from pharma_intake.db import Database
from pharma_intake.ids import format_reference
from pharma_intake.models import AEExtension, IntakeReport, ReporterType, ReportType

SECRET_TEXT = "UNIQUE-FREE-TEXT-MARKER"


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "t.db")


def make(ae=False, desc=SECRET_TEXT):
    return IntakeReport(
        report_type=ReportType.ADVERSE_EVENT if ae else ReportType.QUALITY_COMPLAINT,
        product_name="Examplomab",
        batch_lot="LOT-12345",
        date_received=date(2026, 11, 20),
        reporter_type=ReporterType.CONSUMER,
        description=desc,
        ae=AEExtension(event_description="Fictional event.", onset_date=date(2026, 11, 18))
        if ae
        else None,
    )


def test_reference_format():
    assert format_reference(2026, 7) == "REF-2026-0007"


def test_roundtrip_pqc_and_ae(db):
    r1 = db.create_report(make(), today=date(2026, 11, 23))
    r2 = db.create_report(make(ae=True), today=date(2026, 11, 23))
    assert (r1, r2) == ("REF-2026-0001", "REF-2026-0002")
    row = db.get_report(r2)
    assert row["status"] == "New" and row["onset_date"] == "2026-11-18"
    assert row["event_description"] == "Fictional event."
    assert db.get_report(r1)["onset_date"] is None
    assert db.get_report("REF-2026-9999") is None


def test_references_unique_and_reset_per_year(db):
    refs = [db.create_report(make(), today=date(2026, 1, 1)) for _ in range(5)]
    assert len(set(refs)) == 5
    assert db.create_report(make(), today=date(2027, 1, 1)) == "REF-2027-0001"


def test_list_filters(db):
    db.create_report(make())
    db.create_report(make(ae=True))
    assert len(db.list_reports()) == 2
    assert len(db.list_reports(report_type="Suspected Adverse Event")) == 1
    assert len(db.list_reports(status="Closed")) == 0


def test_audit_written_on_create_without_free_text(db):
    ref = db.create_report(make())
    events = db.audit_events(ref)
    assert [e["action"] for e in events] == ["REPORT_CREATED"]
    assert events[0]["actor"] == "local-user"
    dump = " ".join(str(tuple(e)) for e in db.audit_events())
    assert SECRET_TEXT not in dump


def test_audit_is_append_only(db):
    db.create_report(make())
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_log SET action='X'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_log")
    conn.close()
    assert len(db.audit_events()) == 1


def test_audit_rejects_free_text_detail(db):
    conn = db.connect()
    with pytest.raises(ValueError):
        audit.log_event(conn, "LLM_CALL", detail="a long free text description. " * 5)
    conn.close()


def test_create_is_atomic_when_audit_fails(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("audit down")

    monkeypatch.setattr(audit, "log_event", boom)
    with pytest.raises(RuntimeError):
        db.create_report(make())
    assert db.list_reports() == []
    monkeypatch.undo()
    assert db.create_report(make()) == f"REF-{date.today().year}-0001"  # counter rolled back


def test_status_constraint(db):
    ref = db.create_report(make())
    conn = db.connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE reports SET status='Bogus' WHERE ref=?", (ref,))
    conn.close()
