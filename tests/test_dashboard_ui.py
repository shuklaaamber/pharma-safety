from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from pharma_intake import config
from pharma_intake.db import Database
from pharma_intake.models import AEExtension, IntakeReport, ReporterType, ReportType

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _report(ae):
    return IntakeReport(
        report_type=ReportType.ADVERSE_EVENT if ae else ReportType.QUALITY_COMPLAINT,
        product_name="Examplomab",
        batch_lot="LOT-12345",
        date_received=date(2026, 11, 20),
        reporter_type=ReporterType.CONSUMER,
        description="Fictional.",
        ae=AEExtension(event_description="Fictional event.", onset_date=date(2026, 11, 18))
        if ae
        else None,
    )


@pytest.fixture
def app(tmp_path, monkeypatch):
    path = tmp_path / "d.db"
    monkeypatch.setattr(config, "DB_PATH", path)
    db = Database(path)
    refs = (db.create_report(_report(True)), db.create_report(_report(False)))
    return AppTest.from_file(APP).run(timeout=30), db, refs


def test_empty_dashboard(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "e.db")
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert any("No reports match" in i.value for i in at.info)


def test_filters(app):
    at, _, _ = app
    assert len(at.dataframe[0].value) == 2
    at.selectbox(key="f_type").set_value("Suspected Adverse Event").run()
    assert len(at.dataframe[0].value) == 1
    at.selectbox(key="f_status").set_value("Closed").run()
    assert any("No reports match" in i.value for i in at.info)


def test_full_lifecycle_through_ui(app):
    at, db, (ref_ae, _) = app
    at.selectbox(key="sel_ref").set_value(ref_ae).run()
    at.button(key="btn_review").click().run()
    assert db.get_report(ref_ae)["status"] == "In Review"
    at.button(key="btn_close").click().run()
    assert db.get_report(ref_ae)["status"] == "In Review"  # frozen
    assert any("awaiting human" in w.value for w in at.warning)

    # invalid reviewer ID first: must be rejected and the state stays frozen
    reviewer = [t for t in at.text_input if t.label == "Reviewer ID"][0]
    why = [t for t in at.text_area if t.label == "Decision rationale"][0]
    reviewer.set_value("bad name")
    why.set_value("ok")
    [b for b in at.button if b.label == "Approve closure"][0].click().run()
    assert at.error and db.get_report(ref_ae)["status"] == "In Review"

    reviewer = [t for t in at.text_input if t.label == "Reviewer ID"][0]
    why = [t for t in at.text_area if t.label == "Decision rationale"][0]
    reviewer.set_value("REV-007")
    why.set_value("Documentation complete.")
    [b for b in at.button if b.label == "Approve closure"][0].click().run()
    assert db.get_report(ref_ae)["status"] == "Closed"
    assert any(e["action"] == "CLOSURE_APPROVED" for e in db.audit_events(ref_ae))


def test_audit_tab_lists_events(app):
    at, _, _ = app
    assert len(at.dataframe) == 2  # tracker + audit
    assert len(at.dataframe[1].value) == 2
