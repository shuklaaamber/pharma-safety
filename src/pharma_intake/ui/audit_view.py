"""Audit tab: read-only view of the append-only audit trail."""
from __future__ import annotations

import streamlit as st

from .. import config
from ..db import Database


def render_audit() -> None:
    db = Database(config.DB_PATH)
    ref = st.text_input("Filter by reference (optional)", placeholder="REF-2026-0001")
    events = db.audit_events(ref.strip() or None)
    if not events:
        st.info("No audit events.")
        return
    st.dataframe(
        [
            {
                "ID": e["id"],
                "Timestamp (UTC)": e["ts_utc"],
                "Action": e["action"],
                "Reference": e["ref"],
                "Detail": e["detail"],
                "Actor": e["actor"],
            }
            for e in reversed(events)
        ],
        use_container_width=True,
        hide_index=True,
    )
