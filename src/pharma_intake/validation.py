"""Domain validation: context-sensitive errors, cross-field rules, PII heuristics.

`validate_intake` collects ALL problems up front (so the operator sees every
missing field at once), then builds the strict Pydantic model as a backstop.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from pydantic import ValidationError

from .config import LOT_PATTERN
from .models import AEExtension, IntakeReport, ReporterType, ReportType

# --- PII heuristics (best-effort; synthetic-data guardrail, not a DLP product) ---
_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "an email address": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "a phone number": re.compile(r"(?<!\w)\+?\(?\d[\d\s().-]{8,}\d(?!\w)"),
    "a government/ID number": re.compile(
        r"\b\d{3}-\d{2}-\d{4}\b"
        r"|\b(?:ssn|social security(?: number| no\.?)?|passport(?: number| no\.?)?|national id|"
        r"nhs number|medical record (?:number|no\.?)|mrn)\b",
        re.IGNORECASE,
    ),
    "a date of birth": re.compile(
        r"\b(dob|d\.o\.b|date of birth|born on)\b", re.IGNORECASE
    ),
    "a local phone number": re.compile(r"(?<![\w-])\d{3}[-. ]\d{4}(?![\w-])"),
    "a personal name": re.compile(
        # name cues: case-insensitive, any following word
        r"\b(?i:patient name(?: is)?|my name is|his name is|her name is)\s+(?!(?i:unknown|not|none|n/a|withheld|redacted)\b)[A-Za-z]{2,}"
        r"|\b(?i:name is)\s+[A-Z][a-z]+"
        # titles (capitalised) + capitalised name
        r"|\b(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+[A-Z][a-z]+"
        # "patient: jane" / "pt - jane"
        r"|\b(?i:patient|pt)\s*(?:[:=]|\s-\s)\s*(?!(?i:unknown|not|none|n/a|the|a|an|was|is|has|had|reported|denied|age|aged)\b)[A-Za-z]{2,}"
        # "Patient Smith" (capitalised word that is not ordinary SOP vocabulary)
        r"|\b[Pp]atient\s+(?!(?:Safety|Information|Identifier|Identifiers|Data|Privacy|Name|Names|Age|Outcome|Population|Group|Reported|Report|Reports|Experienced|Complaint|Complaints|Case|Cases|Narrative|Details|Demographics|Health|Support)\b)[A-Z][a-z]{2,}"
        # initials: "J.S." or "J. S."
        r"|\b(?:[A-Z]\.\s?){2,}(?=\s|,|$)|\b(?i:initials?)\s*[:=]?\s*[A-Z]{2,3}\b",
    ),
    "an address": re.compile(
        r"\b\d{1,5}\s+\w+(?:\s\w+)?\s(street|st|road|rd|avenue|ave|lane|ln|drive|dr)\b"
        r"|\b(?:lives|living|resides|residing)\s+(?:in|at|on)\b"
        r"|\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b",
        re.IGNORECASE,
    ),
}


_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def find_pii(text: str) -> list[str]:
    """Return the kinds of personal data the text appears to contain."""
    text = text or ""
    # Dates are legitimate content; remove them so they can't look like phone numbers.
    no_dates = _DATE_RE.sub(" ", text)
    found = []
    for kind, pat in _PII_PATTERNS.items():
        subject = no_dates if "phone" in kind else text
        for m in pat.finditer(subject):
            if kind == "a phone number" and sum(c.isdigit() for c in m.group()) < 10:
                continue
            found.append(kind)
            break
    return found


@dataclass
class ValidationOutcome:
    report: Optional[IntakeReport] = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.report is not None and not self.errors


def _blank(value: Optional[str]) -> bool:
    return value is None or not str(value).strip()


def collect_errors(
    *,
    report_type: str,
    product_name: str,
    batch_lot: str,
    date_received: Optional[date],
    reporter_type: str,
    description: str,
    event_description: str = "",
    onset_date: Optional[date] = None,
    today: Optional[date] = None,
) -> list[str]:
    today = today or date.today()
    errors: list[str] = []

    valid_types = {t.value for t in ReportType}
    if report_type not in valid_types:
        return ["Select a report category: Suspected Adverse Event or Product Quality Complaint."]
    is_ae = report_type == ReportType.ADVERSE_EVENT.value
    label = "adverse event" if is_ae else "quality complaint"

    if _blank(product_name):
        errors.append(f"Product name is required for a {label}.")

    if _blank(batch_lot):
        errors.append(
            f"Batch/lot number is required for a {label}. Use the format LOT-12345."
        )
    elif not re.match(LOT_PATTERN, batch_lot.strip()):
        errors.append(
            "Batch/lot number is not in the expected format. Use LOT- followed by "
            "exactly 5 digits (e.g. LOT-12345)."
        )

    if date_received is None:
        errors.append("Date received is required.")
    elif date_received > today:
        errors.append("Date received cannot be in the future.")

    if reporter_type not in {r.value for r in ReporterType}:
        errors.append("Select a reporter type.")

    if _blank(description):
        errors.append(
            "Detailed description is required: summarise what was reported."
            if is_ae
            else "Detailed description is required: describe the quality issue "
            "(e.g. appearance, packaging, labelling)."
        )

    if is_ae:
        if _blank(event_description):
            errors.append("Event description is required for a Suspected Adverse Event.")
        if onset_date is None:
            errors.append("Event onset date is required for a Suspected Adverse Event.")
        else:
            if onset_date > today:
                errors.append("Event onset date cannot be in the future.")
            if date_received is not None and onset_date > date_received:
                errors.append("Event onset date cannot be after the date received.")

    elif not _blank(event_description) or onset_date is not None:
        errors.append(
            "Event description and onset date apply only to a Suspected Adverse Event. "
            "Remove them, or change the category."
        )

    for fname, text in (
        ("Product name", product_name),
        ("Detailed description", description),
        ("Event description", event_description),
    ):
        for kind in find_pii(text):
            errors.append(
                f"{fname} appears to contain {kind}. Remove personal information; "
                "use fictional data only."
            )
    return errors


def build_report(
    *,
    report_type: str,
    product_name: str,
    batch_lot: str,
    date_received: date,
    reporter_type: str,
    description: str,
    event_description: str = "",
    onset_date: Optional[date] = None,
) -> IntakeReport:
    """Convert raw form values to a strict IntakeReport (raises ValidationError)."""
    rtype = ReportType(report_type)
    ae = None
    if rtype is ReportType.ADVERSE_EVENT:
        ae = AEExtension.model_validate(
            {"event_description": event_description, "onset_date": onset_date}
        )
    return IntakeReport(
        report_type=rtype,
        product_name=product_name,
        batch_lot=batch_lot,
        date_received=date_received,
        reporter_type=ReporterType(reporter_type),
        description=description,
        ae=ae,
    )


def validate_intake(today: Optional[date] = None, **raw) -> ValidationOutcome:
    errors = collect_errors(today=today, **raw)
    if errors:
        return ValidationOutcome(errors=errors)
    try:
        return ValidationOutcome(report=build_report(**raw))
    except ValidationError as exc:  # backstop: should be unreachable after collect_errors
        return ValidationOutcome(
            errors=[
                f"{'.'.join(str(p) for p in e['loc']) or 'report'}: {e['msg']}"
                for e in exc.errors()
            ]
        )
