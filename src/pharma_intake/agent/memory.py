"""Step 2: dual-memory engine.

Short-term: volatile ReAct (Thought-Action-Observation) trace, per session, bounded,
never persisted. Long-term: durable state read from SQLite (reports + audit).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..db import Database

OBS_MAX = 240


@dataclass(frozen=True)
class TraceStep:
    thought: str
    action: str
    observation: str


class ShortTermMemory:
    def __init__(self, max_steps: int = 50):
        self.max_steps = max_steps
        self.steps: list[TraceStep] = []

    def add(self, thought: str, action: str, observation: str) -> None:
        self.steps.append(TraceStep(thought, action, observation[:OBS_MAX]))
        del self.steps[: -self.max_steps]

    def clear(self) -> None:
        self.steps.clear()


class LongTermMemory:
    def __init__(self, db: Database):
        self.db = db

    def report_state(self, ref: str) -> Optional[dict]:
        row = self.db.get_report(ref)
        if row is None:
            return None
        from ..workflow import pending_approval

        return {
            "ref": ref,
            "status": row["status"],
            "report_type": row["report_type"],
            "pending_approval": pending_approval(self.db, ref),
            "audit_events": len(self.db.audit_events(ref)),
        }
