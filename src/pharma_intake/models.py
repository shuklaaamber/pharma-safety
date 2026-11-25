"""Pydantic v2 schemas for intake reports.

Deliberately contains NO patient-identifier fields. Field-level format rules live
here; context-sensitive error wording and PII heuristics arrive in validation.py
(Milestone C).
"""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .config import LOT_PATTERN


class ReportType(str, Enum):
    ADVERSE_EVENT = "Suspected Adverse Event"
    QUALITY_COMPLAINT = "Product Quality Complaint"


class ReporterType(str, Enum):
    HEALTHCARE_PROFESSIONAL = "Healthcare Professional"
    PHARMACIST = "Pharmacist"
    CONSUMER = "Consumer"
    DISTRIBUTOR = "Distributor"
    SALES_REPRESENTATIVE = "Sales Representative"
    OTHER = "Other"


class _Base(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)


class AEExtension(_Base):
    """Adverse-event-only fields. No patient identifiers are collected."""

    event_description: str = Field(min_length=1, max_length=2000)
    onset_date: date


class IntakeReport(_Base):
    report_type: ReportType
    product_name: str = Field(min_length=1, max_length=200)
    batch_lot: str = Field(pattern=LOT_PATTERN)
    date_received: date
    reporter_type: ReporterType
    description: str = Field(min_length=1, max_length=4000)
    ae: Optional[AEExtension] = None

    @model_validator(mode="after")
    def _ae_extension_matches_type(self) -> "IntakeReport":
        is_ae = self.report_type is ReportType.ADVERSE_EVENT
        if is_ae and self.ae is None:
            raise ValueError(
                "Adverse event details (event description and onset date) are "
                "required for a Suspected Adverse Event."
            )
        if not is_ae and self.ae is not None:
            raise ValueError(
                "Adverse event details must not be supplied for a Product Quality "
                "Complaint."
            )
        return self
