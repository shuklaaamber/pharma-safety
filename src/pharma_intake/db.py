"""SQLite persistence. All SQL is parametrized."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from . import audit
from .ids import next_reference
from .models import IntakeReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    ref               TEXT PRIMARY KEY,
    report_type       TEXT NOT NULL CHECK (report_type IN
                        ('Suspected Adverse Event','Product Quality Complaint')),
    product_name      TEXT NOT NULL,
    batch_lot         TEXT NOT NULL,
    date_received     TEXT NOT NULL,
    reporter_type     TEXT NOT NULL,
    description       TEXT NOT NULL,
    event_description TEXT,
    onset_date        TEXT,
    status            TEXT NOT NULL DEFAULT 'New'
                        CHECK (status IN ('New','In Review','Closed')),
    created_at        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ref           TEXT NOT NULL REFERENCES reports(ref),
    requested_at  TEXT NOT NULL,
    decision      TEXT NOT NULL CHECK (decision IN ('Pending','Approved','Rejected')),
    decided_at    TEXT,
    reviewer_id   TEXT,
    reviewer_role TEXT,
    rationale     TEXT
);
-- at most one open (Pending/Approved) approval per report
CREATE UNIQUE INDEX IF NOT EXISTS one_open_approval ON approvals(ref)
    WHERE decision IN ('Pending','Approved');
CREATE TRIGGER IF NOT EXISTS approvals_decide_once BEFORE UPDATE ON approvals
WHEN OLD.decision != 'Pending'
BEGIN SELECT RAISE(ABORT, 'approval decision is final'); END;
CREATE TRIGGER IF NOT EXISTS approvals_no_delete BEFORE DELETE ON approvals
BEGIN SELECT RAISE(ABORT, 'approvals are append-only'); END;
-- approvals can only be OPENED as Pending, and only for a report that is In Review
CREATE TRIGGER IF NOT EXISTS approvals_insert_pending BEFORE INSERT ON approvals
WHEN NEW.decision != 'Pending'
    OR COALESCE((SELECT status FROM reports WHERE ref = NEW.ref), '') != 'In Review'
BEGIN SELECT RAISE(ABORT, 'approval must open as Pending on an In Review report'); END;
-- a decision needs a pseudonymous reviewer ID and a non-empty rationale; identity fields are fixed
CREATE TRIGGER IF NOT EXISTS approvals_decision_complete BEFORE UPDATE ON approvals
WHEN OLD.decision = 'Pending' AND (
    NEW.ref != OLD.ref OR NEW.requested_at != OLD.requested_at
    OR (NEW.decision IN ('Approved','Rejected') AND (
        NEW.reviewer_id IS NULL OR NEW.reviewer_id NOT GLOB 'REV-[0-9][0-9][0-9]'
        OR NEW.rationale IS NULL OR trim(NEW.rationale) = '' OR NEW.decided_at IS NULL)))
BEGIN SELECT RAISE(ABORT, 'decision requires reviewer ID, rationale and timestamp'); END;
-- reports always start as New
CREATE TRIGGER IF NOT EXISTS reports_insert_new BEFORE INSERT ON reports
WHEN NEW.status != 'New'
BEGIN SELECT RAISE(ABORT, 'reports must be created as New'); END;
-- DB-level guard: only New->In Review, or In Review->Closed WITH an approved sign-off.
CREATE TRIGGER IF NOT EXISTS reports_status_guard BEFORE UPDATE OF status ON reports
WHEN NOT (
    (OLD.status = 'New' AND NEW.status = 'In Review')
    OR (OLD.status = 'In Review' AND NEW.status = 'Closed'
        AND EXISTS (SELECT 1 FROM approvals
                    WHERE ref = OLD.ref AND decision = 'Approved'))
)
BEGIN SELECT RAISE(ABORT, 'illegal status transition'); END;
CREATE TABLE IF NOT EXISTS ref_counter (
    year INTEGER PRIMARY KEY,
    last INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc  TEXT NOT NULL,
    action  TEXT NOT NULL,
    ref     TEXT,
    detail  TEXT,
    actor   TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def create_report(self, report: IntakeReport, today: Optional[date] = None) -> str:
        """Atomically allocate a REF, store the report and write the audit entry."""
        today = today or date.today()
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            with conn:  # commit on success, rollback on any error
                ref = next_reference(conn, today.year)
                conn.execute(
                    "INSERT INTO reports (ref, report_type, product_name, batch_lot,"
                    " date_received, reporter_type, description, event_description,"
                    " onset_date, status, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ref,
                        report.report_type.value,
                        report.product_name,
                        report.batch_lot,
                        report.date_received.isoformat(),
                        report.reporter_type.value,
                        report.description,
                        report.ae.event_description if report.ae else None,
                        report.ae.onset_date.isoformat() if report.ae else None,
                        "New",
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    ),
                )
                audit.log_event(conn, "REPORT_CREATED", ref=ref, detail=report.report_type.value)
            return ref
        finally:
            conn.close()

    def log_audit(self, action: str, ref: Optional[str] = None, detail: Optional[str] = None,
                  actor: str = audit.ACTOR_DEFAULT) -> None:
        conn = self.connect()
        try:
            with conn:
                audit.log_event(conn, action, ref=ref, detail=detail, actor=actor)
        finally:
            conn.close()

    def get_report(self, ref: str) -> Optional[sqlite3.Row]:
        conn = self.connect()
        try:
            return conn.execute("SELECT * FROM reports WHERE ref = ?", (ref,)).fetchone()
        finally:
            conn.close()

    def list_reports(
        self, status: Optional[str] = None, report_type: Optional[str] = None
    ) -> list[sqlite3.Row]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if report_type:
            clauses.append("report_type = ?")
            params.append(report_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        conn = self.connect()
        try:
            return conn.execute(
                f"SELECT * FROM reports {where} ORDER BY created_at DESC, ref DESC", params
            ).fetchall()
        finally:
            conn.close()

    def audit_events(self, ref: Optional[str] = None) -> list[sqlite3.Row]:
        conn = self.connect()
        try:
            return audit.list_events(conn, ref)
        finally:
            conn.close()
