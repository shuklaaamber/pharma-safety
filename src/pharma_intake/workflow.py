"""Status lifecycle: New -> In Review -> Closed, with a human-in-the-loop gate.

In Review -> Closed never happens in one step: a closure is REQUESTED (report
stays In Review, state frozen) and only an explicit, recorded reviewer decision
completes it. The same rule is enforced again by a database trigger.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from . import audit
from .db import Database
from .validation import find_pii

REVIEWER_ROLES = ("Compliance Reviewer", "QA Lead")
# Pseudonymous reviewer IDs only (no personal names).
REVIEWER_ID_RE = re.compile(r"^REV-\d{3}$")
RATIONALE_MAX = 200


@dataclass(frozen=True)
class WorkflowResult:
    ok: bool
    message: str
    status: Optional[str] = None
    pending_approval: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fail(msg: str, status: Optional[str] = None, pending: bool = False) -> WorkflowResult:
    return WorkflowResult(False, msg, status, pending)


def _pending(conn: sqlite3.Connection, ref: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM approvals WHERE ref=? AND decision='Pending'", (ref,)
    ).fetchone()


def pending_approval(db: Database, ref: str) -> bool:
    conn = db.connect()
    try:
        return _pending(conn, ref) is not None
    finally:
        conn.close()


def pending_refs(db: Database) -> list[str]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT ref FROM approvals WHERE decision='Pending' ORDER BY id"
        ).fetchall()
        return [r["ref"] for r in rows]
    finally:
        conn.close()


def request_status_change(db: Database, ref: str, target: str) -> WorkflowResult:
    """Move New -> In Review, or request closure (HITL) from In Review."""
    conn = db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        with conn:
            row = conn.execute("SELECT status FROM reports WHERE ref=?", (ref,)).fetchone()
            if row is None:
                return _fail(f"Report {ref} was not found.")
            current = row["status"]

            if current == "Closed":
                return _fail("This report is Closed and cannot be changed.", current)
            if target == "In Review" and current == "New":
                conn.execute("UPDATE reports SET status='In Review' WHERE ref=?", (ref,))
                audit.log_event(conn, "STATUS_CHANGED", ref=ref, detail="New>In Review")
                return WorkflowResult(True, f"{ref} moved to In Review.", "In Review")
            if target == "Closed" and current == "In Review":
                if _pending(conn, ref):
                    return _fail(
                        "A closure approval is already pending for this report.",
                        current,
                        True,
                    )
                conn.execute(
                    "INSERT INTO approvals (ref, requested_at, decision) VALUES (?,?,'Pending')",
                    (ref, _now()),
                )
                audit.log_event(conn, "CLOSURE_REQUESTED", ref=ref, detail="In Review>Closed")
                return WorkflowResult(
                    True,
                    f"Closure requested. {ref} stays In Review until a reviewer approves.",
                    current,
                    True,
                )
            if target == "Closed" and current == "New":
                return _fail("A New report must go to In Review before it can be Closed.", current)
            return _fail(
                f"Transition {current} -> {target} is not allowed. "
                "Allowed order: New -> In Review -> Closed.",
                current,
            )
    finally:
        conn.close()


def decide_closure(
    db: Database,
    ref: str,
    decision: str,
    reviewer_id: str,
    reviewer_role: str,
    rationale: str,
) -> WorkflowResult:
    """Record the human reviewer's decision on a pending closure."""
    reviewer_id = (reviewer_id or "").strip()
    rationale = (rationale or "").strip()
    if decision not in ("Approved", "Rejected"):
        return _fail("Decision must be Approved or Rejected.")
    if not REVIEWER_ID_RE.match(reviewer_id):
        return _fail("Reviewer ID must use the pseudonymous format REV-123 (no names).")
    if reviewer_role not in REVIEWER_ROLES:
        return _fail("Select a valid reviewer role.")
    if not rationale:
        return _fail("A rationale is required to record the decision.")
    if len(rationale) > RATIONALE_MAX:
        return _fail(f"Rationale must be at most {RATIONALE_MAX} characters.")
    if find_pii(rationale):
        return _fail("Rationale appears to contain personal information; remove it.")

    conn = db.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        with conn:
            row = conn.execute("SELECT status FROM reports WHERE ref=?", (ref,)).fetchone()
            if row is None:
                return _fail(f"Report {ref} was not found.")
            pend = _pending(conn, ref)
            if row["status"] != "In Review" or pend is None:
                return _fail("There is no pending closure request for this report.", row["status"])
            conn.execute(
                "UPDATE approvals SET decision=?, decided_at=?, reviewer_id=?,"
                " reviewer_role=?, rationale=? WHERE id=?",
                (decision, _now(), reviewer_id, reviewer_role, rationale, pend["id"]),
            )
            if decision == "Approved":
                conn.execute("UPDATE reports SET status='Closed' WHERE ref=?", (ref,))
                audit.log_event(
                    conn, "CLOSURE_APPROVED", ref=ref, detail="In Review>Closed", actor=reviewer_id
                )
                return WorkflowResult(True, f"{ref} approved and Closed.", "Closed")
            audit.log_event(
                conn, "CLOSURE_REJECTED", ref=ref, detail="stays In Review", actor=reviewer_id
            )
            return WorkflowResult(True, f"Closure rejected. {ref} stays In Review.", "In Review")
    finally:
        conn.close()
