"""Streamlit UI entry point (thin; business logic lives in src/pharma_intake)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

from pharma_intake.config import SYNTHETIC_BANNER  # noqa: E402
from pharma_intake.ui.ask import render_ask  # noqa: E402
from pharma_intake.ui.audit_view import render_audit  # noqa: E402
from pharma_intake.ui.dashboard import render_dashboard  # noqa: E402
from pharma_intake.ui.intake_form import render_intake_form  # noqa: E402

st.set_page_config(page_title="Pharma Safety Intake Tracker", layout="wide")
st.title("Pharma Safety Intake & Triage Tracker")
st.warning(SYNTHETIC_BANNER)

intake_tab, dashboard_tab, ask_tab, audit_tab = st.tabs(
    ["Intake", "Dashboard", "Ask", "Audit"]
)

with intake_tab:
    render_intake_form()
with dashboard_tab:
    render_dashboard()
with ask_tab:
    render_ask()
with audit_tab:
    render_audit()
