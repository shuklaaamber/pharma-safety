from datetime import date

import pytest

from pharma_intake.validation import find_pii, validate_intake

TODAY = date(2026, 11, 23)
OK = dict(
    report_type="Product Quality Complaint",
    product_name="Examplomab",
    batch_lot="LOT-12345",
    date_received=date(2026, 11, 20),
    reporter_type="Consumer",
    description="Tablet blister packaging was torn.",
)
AE_OK = {
    **OK,
    "report_type": "Suspected Adverse Event",
    "event_description": "Fictional rash reported.",
    "onset_date": date(2026, 11, 18),
}


def run(**over):
    return validate_intake(today=TODAY, **{**OK, **over})


def run_ae(**over):
    return validate_intake(today=TODAY, **{**AE_OK, **over})


def test_valid_pqc_and_ae():
    assert run().ok
    assert run_ae().ok


def test_all_missing_fields_reported_at_once():
    out = run(product_name="", batch_lot="", description="")
    assert len(out.errors) == 3
    assert any("Product name is required" in e for e in out.errors)
    assert any("Batch/lot number is required" in e and "LOT-12345" in e for e in out.errors)


def test_messages_are_context_sensitive():
    pqc = run(description="").errors[0]
    ae = run_ae(description="").errors[0]
    assert "quality issue" in pqc
    assert "summarise" in ae
    assert "quality complaint" in run(product_name="").errors[0]
    assert "adverse event" in run_ae(product_name="").errors[0]


@pytest.mark.parametrize("lot", ["LOT-1234", "lot-12345", "LOT-123456", "ABC"])
def test_bad_lot_format_message(lot):
    out = run(batch_lot=lot)
    assert not out.ok and "5 digits" in out.errors[0]


def test_ae_requires_event_fields():
    out = run_ae(event_description="", onset_date=None)
    assert len(out.errors) == 2


def test_onset_after_received_rejected():
    out = run_ae(onset_date=date(2026, 11, 21))
    assert any("after the date received" in e for e in out.errors)


def test_future_dates_rejected():
    assert any("future" in e for e in run(date_received=date(2026, 12, 1)).errors)
    assert any("future" in e for e in run_ae(onset_date=date(2027, 1, 1)).errors)


def test_pqc_without_ae_fields_is_ok():
    out = run(event_description="", onset_date=None)
    assert out.ok and out.report.ae is None


@pytest.mark.parametrize(
    "text, kind",
    [
        ("contact jane.doe@example.com", "email"),
        ("call 555-123-4567 today", "phone"),
        ("SSN 123-45-6789", "ID"),
        ("DOB 01/02/1980", "birth"),
        ("my name is Alice", "name"),
        ("Patient: Bob reported", "name"),
        ("lives at 12 Oak Street", "address"),
    ],
)
def test_pii_detected(text, kind):
    assert any(kind in k for k in find_pii(text))
    out = run(description=text)
    assert not out.ok and any("fictional data only" in e for e in out.errors)


def test_no_false_positive_on_lot_dates_and_plain_text():
    for text in ["LOT-88392 anaphylaxis", "Received 2026-10-30", "Blister torn, 10 tablets"]:
        assert find_pii(text) == []
