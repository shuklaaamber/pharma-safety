from datetime import date

import pytest
from pydantic import ValidationError

from pharma_intake.models import AEExtension, IntakeReport, ReporterType, ReportType
from pharma_intake.validation import build_report

BASE = dict(
    product_name="Examplomab",
    batch_lot="LOT-12345",
    date_received=date(2026, 11, 1),
    reporter_type=ReporterType.CONSUMER,
    description="Fictional description.",
)
AE = AEExtension(event_description="Fictional event.", onset_date=date(2026, 10, 30))


def test_valid_quality_complaint():
    r = IntakeReport(report_type=ReportType.QUALITY_COMPLAINT, **BASE)
    assert r.ae is None


def test_valid_adverse_event():
    r = IntakeReport(report_type=ReportType.ADVERSE_EVENT, ae=AE, **BASE)
    assert r.ae.onset_date == date(2026, 10, 30)


@pytest.mark.parametrize("lot", ["LOT-1234", "lot-12345", "LOT-123456", "12345", ""])
def test_bad_lot_rejected(lot):
    with pytest.raises(ValidationError):
        IntakeReport(
            report_type=ReportType.QUALITY_COMPLAINT, **{**BASE, "batch_lot": lot}
        )


@pytest.mark.parametrize("field", list(BASE))
def test_missing_core_field_rejected(field):
    data = {k: v for k, v in BASE.items() if k != field}
    with pytest.raises(ValidationError):
        IntakeReport(report_type=ReportType.QUALITY_COMPLAINT, **data)


def test_ae_requires_extension():
    with pytest.raises(ValidationError, match="Adverse event details"):
        IntakeReport(report_type=ReportType.ADVERSE_EVENT, **BASE)


def test_pqc_rejects_extension():
    with pytest.raises(ValidationError, match="must not be supplied"):
        IntakeReport(report_type=ReportType.QUALITY_COMPLAINT, ae=AE, **BASE)


def test_unknown_field_rejected_so_no_patient_identifiers():
    with pytest.raises(ValidationError):
        IntakeReport(
            report_type=ReportType.QUALITY_COMPLAINT, patient_name="x", **BASE
        )


def test_whitespace_only_text_rejected():
    with pytest.raises(ValidationError):
        IntakeReport(
            report_type=ReportType.QUALITY_COMPLAINT, **{**BASE, "product_name": "   "}
        )


def test_build_report_from_form_strings():
    r = build_report(
        report_type="Suspected Adverse Event",
        product_name="Examplomab",
        batch_lot="LOT-12345",
        date_received=date(2026, 11, 1),
        reporter_type="Pharmacist",
        description="Fictional.",
        event_description="Fictional event.",
        onset_date=date(2026, 10, 30),
    )
    assert r.reporter_type is ReporterType.PHARMACIST and r.ae is not None


def test_build_report_ae_missing_onset_date():
    with pytest.raises(ValidationError):
        build_report(
            report_type="Suspected Adverse Event",
            product_name="Examplomab",
            batch_lot="LOT-12345",
            date_received=date(2026, 11, 1),
            reporter_type="Consumer",
            description="Fictional.",
            event_description="Fictional event.",
            onset_date=None,
        )
