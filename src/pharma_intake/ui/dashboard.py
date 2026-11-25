"""Dashboard tab: tracker table, filters, status panel with HITL approval."""
from __future__ import annotations

import streamlit as st

from .. import config, workflow
from ..db import Database
from .safe_text import escape_md

ALL = "All"
COLUMNS = {
    "ref": "Reference",
    "report_type": "Type",
    "product_name": "Product",
    "batch_lot": "Batch/Lot",
    "date_received": "Date received",
    "reporter_type": "Reporter",
    "status": "Status",
}


def _flash() -> None:
    msg = st.session_state.pop("flash", None)
    if msg:
        (st.success if msg[0] else st.error)(msg[1])


def _apply(result: workflow.WorkflowResult) -> None:
    st.session_state["flash"] = (result.ok, result.message)
    st.rerun()


def render_dashboard() -> None:
    db = Database(config.DB_PATH)
    _flash()

    c1, c2 = st.columns(2)
    status = c1.selectbox("Filter by status", [ALL, *config.STATUSES], key="f_status")
    rtype = c2.selectbox("Filter by report type", [ALL, *config.REPORT_TYPES], key="f_type")
    rows = db.list_reports(
        status=None if status == ALL else status,
        report_type=None if rtype == ALL else rtype,
    )

    if not rows:
        st.info("No reports match the current filters.")
        return
    st.dataframe(
        [{label: r[key] for key, label in COLUMNS.items()} for r in rows],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Review & status")
    ref = st.selectbox("Select a report", [r["ref"] for r in rows], key="sel_ref")
    report = db.get_report(ref)
    st.write(f"**Status:** {report['status']}  |  **Type:** {report['report_type']}")
    st.caption(f"Description: {escape_md(report['description'])}")
    if report["event_description"]:
        st.caption(
            f"Event: {escape_md(report['event_description'])} (onset {report['onset_date']})"
        )

    current = report["status"]
    pending = workflow.pending_approval(db, ref)
    if current == "New":
        if st.button("Move to In Review", key="btn_review"):
            _apply(workflow.request_status_change(db, ref, "In Review"))
    elif current == "In Review" and not pending:
        if st.button("Request closure", key="btn_close"):
            _apply(workflow.request_status_change(db, ref, "Closed"))
    elif current == "In Review" and pending:
        st.warning(
            "Closure is awaiting human compliance approval. The report is frozen "
            "in In Review until a reviewer decides."
        )
        with st.form("approval_form"):
            reviewer_id = st.text_input("Reviewer ID", placeholder="REV-001")
            role = st.selectbox("Reviewer role", workflow.REVIEWER_ROLES)
            rationale = st.text_area(
                "Decision rationale", max_chars=workflow.RATIONALE_MAX
            )
            a, r = st.columns(2)
            approve = a.form_submit_button("Approve closure")
            reject = r.form_submit_button("Reject closure")
        if approve or reject:
            _apply(
                workflow.decide_closure(
                    db,
                    ref,
                    "Approved" if approve else "Rejected",
                    reviewer_id,
                    role,
                    rationale,
                )
            )
    else:
        st.info("This report is Closed and cannot be changed.")
