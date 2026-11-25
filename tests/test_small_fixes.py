"""Regression tests for findings 6, 8, 10 and 11 of docs/review-evidence.md."""
import glob
import re
from datetime import date
from pathlib import Path

import pytest

from pharma_intake import config
from pharma_intake.agent.orchestrator import AgentOrchestrator
from pharma_intake.agent.router import is_status_command
from pharma_intake.db import Database
from pharma_intake.models import IntakeReport, ReporterType, ReportType
from pharma_intake.rag.pipeline import HybridRetriever
from pharma_intake.ui.safe_text import escape_md
from pharma_intake.validation import find_pii, validate_intake

ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ finding 6: PII
@pytest.mark.parametrize(
    "text",
    [
        "my name is john smith",
        "Patient Smith reported a rash",
        "patient: jane",
        "J.S. aged 54 male",
        "Jane Doe, 12 Oak, call 555-1234",
        "lives in Springfield, IL 62704",
        "SSN 123456789",
        "Mr Brown called back",
        "His name is bob",
    ],
)
def test_pii_gaps_from_review_are_now_caught(text):
    assert find_pii(text)


@pytest.mark.parametrize(
    "text",
    [
        "The product name is unknown",
        "file name is attached",
        "Patient Safety team reviews LOT-12345",
        "patient reported a headache",
        "patient: unknown",
        "Blister packaging was torn on 2026-11-20",
        "Examplomab LOT-88392 anaphylaxis",
        "a 5 ms delay was observed",
    ],
)
def test_pii_scan_does_not_flag_ordinary_text(text):
    assert find_pii(text) == []


def test_known_limit_bare_names_are_not_detected():
    """Documented limit: a bare name with no cue word cannot be found by regex."""
    assert find_pii("Jane Doe felt dizzy") == []


def test_synthetic_sops_do_not_trigger_the_pii_scan():
    """The same scanner guards outbound LLM text; SOP chunks must never block it."""
    files = glob.glob(str(ROOT / "data" / "sops" / "*.md"))
    assert files
    for f in files:
        assert find_pii(Path(f).read_text(encoding="utf-8")) == [], f


# --------------------------------------------------------------- finding 8: PQC + AE
def _pqc(**over):
    base = dict(
        report_type="Product Quality Complaint", product_name="Examplomab",
        batch_lot="LOT-12345", date_received=date(2026, 11, 20), reporter_type="Consumer",
        description="Blister packaging was torn", today=date(2026, 11, 23),
    )
    base.update(over)
    return validate_intake(**base)


def test_pqc_with_ae_fields_is_rejected_with_explicit_message():
    out = _pqc(event_description="Rash", onset_date=date(2026, 11, 19))
    assert not out.ok and any("apply only to a Suspected Adverse Event" in e for e in out.errors)


def test_pqc_with_only_onset_date_is_rejected_too():
    assert not _pqc(onset_date=date(2026, 11, 19)).ok


def test_pqc_without_ae_fields_still_saves():
    assert _pqc().ok


# ---------------------------------------------------- finding 10: questions are read-only
@pytest.mark.parametrize(
    "text, expected",
    [
        ("move REF-2026-0001 to in review", True),
        ("Please close REF-2026-0001", True),
        ("close ref-2026-0007 please", True),
        ("What is the status of REF-2026-0001 and does the SOP review period apply?", False),
        ("Can you tell me if REF-2026-0001 was reviewed?", False),
        ("REF-2026-0001 was moved to review yesterday", False),
        ("status of REF-2026-0001", False),
    ],
)
def test_is_status_command(text, expected):
    assert is_status_command(text) is expected


def test_question_mentioning_a_ref_does_not_change_status(tmp_path):
    db = Database(tmp_path / "q.db")
    ref = db.create_report(
        IntakeReport(
            report_type=ReportType.QUALITY_COMPLAINT, product_name="Examplomab",
            batch_lot="LOT-12345", date_received=date(2026, 11, 20),
            reporter_type=ReporterType.CONSUMER, description="Fictional.",
        )
    )
    agent = AgentOrchestrator(db, lambda: HybridRetriever([]))
    reply = agent.handle(f"What is the status of {ref} and does the SOP review period apply?")
    assert "status New" in reply.text
    assert db.get_report(ref)["status"] == "New"
    assert [r["action"] for r in db.audit_events()] == ["REPORT_CREATED"]
    agent.handle(f"move {ref} to in review")  # an explicit command still works
    assert db.get_report(ref)["status"] == "In Review"


# --------------------------------------------------------------------- finding 11
def test_lot_pattern_rejects_non_ascii_digits():
    assert re.match(config.LOT_PATTERN, "LOT-12345")
    fullwidth = "LOT-" + "".join(chr(0xFF11 + i) for i in range(5))
    assert not re.match(config.LOT_PATTERN, fullwidth)
    assert not validate_intake(
        report_type="Product Quality Complaint", product_name="Examplomab", batch_lot=fullwidth,
        date_received=date(2026, 11, 20), reporter_type="Consumer", description="x",
        today=date(2026, 11, 23),
    ).ok


def test_gitignore_covers_sqlite_sidecar_files():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert "data/*.db" in lines and "data/*.db-*" in lines and ".env" in lines and "logs/" in lines


def test_escape_md_neutralises_links_images_and_directives():
    hostile = "![x](https://evil.example/a.png) [click](http://x) :smile: $E=mc^2$ <b>hi</b> *bold*"
    out = escape_md(hostile)
    backslash = chr(92)
    for ch in "![]()<>*:$":
        for m in re.finditer(re.escape(ch), out):
            assert out[m.start() - 1] == backslash, (ch, out)
    assert escape_md("line1" + chr(10) + "line2") == "line1  " + chr(10) + "line2"
    assert escape_md("") == "" and escape_md(None) == ""
