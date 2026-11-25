"""Unique reference generator: REF-YYYY-XXXX (per-year sequence)."""
from __future__ import annotations

import sqlite3


def format_reference(year: int, number: int) -> str:
    return f"REF-{year}-{number:04d}"


def next_reference(conn: sqlite3.Connection, year: int) -> str:
    """Allocate the next reference. Must run inside the caller's write transaction
    (db.create_report opens BEGIN IMMEDIATE) so concurrent writers cannot collide."""
    conn.execute(
        "INSERT INTO ref_counter (year, last) VALUES (?, 0) ON CONFLICT(year) DO NOTHING",
        (year,),
    )
    conn.execute("UPDATE ref_counter SET last = last + 1 WHERE year = ?", (year,))
    (last,) = conn.execute("SELECT last FROM ref_counter WHERE year = ?", (year,)).fetchone()
    return format_reference(year, last)
