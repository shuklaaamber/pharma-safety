"""Streamlit intake form: collects input, delegates validation and storage."""
from __future__ import annotations

from datetime import date

import streamlit as st

from .. import config
from ..db import Database
from ..models import ReporterType, ReportType
from ..validation import validate_intake


def render_intake_form() -> None:
    # Category sits outside the form so AE fields appear immediately on change.
    report_type = st.radio(
        "Report category", [t.value for t in ReportType], horizontal=True
    )
    is_ae = report_type == ReportType.ADVERSE_EVENT.value

    with st.form("intake_form"):
        product_name = st.text_input("Product name")
        batch_lot = st.text_input("Batch / lot number", placeholder="LOT-12345")
        date_received = st.date_input("Date received", value=date.today())
        reporter_type = st.selectbox("Reporter type", [r.value for r in ReporterType])
        description = st.text_area(
            "Detailed description",
            help="Fictional data only. Do not enter names, contact details or medical history.",
        )
        event_description, onset_date = "", None
        if is_ae:
            st.subheader("Adverse event details")
            event_description = st.text_area(
                "Event description (no patient identifiers)"
            )
            onset_date = st.date_input("Event onset date", value=None)
        submitted = st.form_submit_button("Submit report")

    if not submitted:
        return

    outcome = validate_intake(
        report_type=report_type,
        product_name=product_name,
        batch_lot=batch_lot,
        date_received=date_received,
        reporter_type=reporter_type,
        description=description,
        event_description=event_description,
        onset_date=onset_date,
    )
    if not outcome.ok:
        st.error("Report not saved. Please fix the following:")
        for msg in outcome.errors:
            st.markdown(f"- {msg}")
        return

    ref = Database(config.DB_PATH).create_report(outcome.report)
    st.success(f"Report saved with reference **{ref}** (status: New).")
