"""Append-only audit trail.

Stores WHAT happened, WHEN, and to WHICH reference only. Never free text:
descriptions, event text and reviewer rationale must not be passed in.
UPDATE/DELETE are blocked by database triggers (see db.SCHEMA).
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

ACTOR_DEFAULT = "local-user"  # role label only; no personal identifiers
# `detail` is for controlled vocabulary (report type, status values) only.
_DETAIL_RE = re.compile(r"^[A-Za-z0-9 _:>./\-]{0,60}$")
# Closed vocabularies: anything else is rejected rather than stored.
ACTIONS = frozenset({
    "REPORT_CREATED", "STATUS_CHANGED", "CLOSURE_REQUESTED", "CLOSURE_APPROVED",
    "CLOSURE_REJECTED", "CIRCUIT_BREAKER_TRIPPED", "LLM_CALL",
})
_REF_RE = re.compile(r"^REF-\d{4}-\d{4,}$")
_ACTOR_RE = re.compile(rf"^(?:{re.escape(ACTOR_DEFAULT)}|REV-\d{{3}})$")


def log_event(
    conn: sqlite3.Connection,
    action: str,
    ref: Optional[str] = None,
    detail: Optional[str] = None,
    actor: str = ACTOR_DEFAULT,
) -> None:
    if action not in ACTIONS:
        raise ValueError("Audit action is not in the controlled vocabulary.")
    if ref is not None and not _REF_RE.match(ref):
        raise ValueError("Audit ref must be a REF-YYYY-XXXX identifier.")
    if not _ACTOR_RE.match(actor):
        raise ValueError("Audit actor must be the local-user label or a REV-### ID.")
    if detail is not None and not _DETAIL_RE.match(detail):
        raise ValueError("Audit detail must be short controlled text, not free text.")
    conn.execute(
        "INSERT INTO audit_log (ts_utc, action, ref, detail, actor) VALUES (?,?,?,?,?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            action,
            ref,
            detail,
            actor,
        ),
    )


def list_events(conn: sqlite3.Connection, ref: Optional[str] = None) -> list[sqlite3.Row]:
    if ref:
        cur = conn.execute("SELECT * FROM audit_log WHERE ref=? ORDER BY id", (ref,))
    else:
        cur = conn.execute("SELECT * FROM audit_log ORDER BY id")
    return cur.fetchall()
