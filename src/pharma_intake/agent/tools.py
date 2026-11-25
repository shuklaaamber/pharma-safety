"""Step 1: type-safe tool validation (Pydantic schemas + deterministic auto-repair).

Tools exposed to the agent: submit_intake_report, update_status, rag_lookup.
There is deliberately NO tool that approves a closure: the human-in-the-loop
decision is only reachable through the dashboard (workflow.decide_closure).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import workflow
from ..config import LOT_PATTERN
from ..db import Database
from ..models import ReporterType, ReportType
from ..rag.generator import LLMClient, generate_answer
from ..rag.pipeline import HybridRetriever
from ..validation import validate_intake

REF_PATTERN = r"^REF-\d{4}-\d{4,}$"
INVALID_ARG_CODES = frozenset({"VALIDATION_ERROR", "DOMAIN_VALIDATION", "UNKNOWN_TOOL"})


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SubmitIntakeArgs(_Args):
    report_type: ReportType
    product_name: str = Field(min_length=1, max_length=200)
    batch_lot: str = Field(pattern=LOT_PATTERN)
    date_received: date
    reporter_type: ReporterType
    description: str = Field(min_length=1, max_length=4000)
    event_description: Optional[str] = Field(default=None, max_length=2000)
    onset_date: Optional[date] = None


class UpdateStatusArgs(_Args):
    ref: str = Field(pattern=REF_PATTERN)
    target_status: str = Field(pattern=r"^(In Review|Closed)$")


class RagLookupArgs(_Args):
    query: str = Field(min_length=2, max_length=500)


SCHEMAS: dict[str, type[_Args]] = {
    "submit_intake_report": SubmitIntakeArgs,
    "update_status": UpdateStatusArgs,
    "rag_lookup": RagLookupArgs,
}

ALIASES = {
    "batch_id": "batch_lot", "batch": "batch_lot", "lot": "batch_lot",
    "lot_number": "batch_lot", "batch_number": "batch_lot", "lot_id": "batch_lot",
    "product": "product_name", "type": "report_type", "category": "report_type",
    "received": "date_received", "date": "date_received", "reporter": "reporter_type",
    "desc": "description", "details": "description", "onset": "onset_date",
    "event": "event_description", "status": "target_status", "new_status": "target_status",
    "reference": "ref", "id": "ref", "report_id": "ref", "q": "query", "question": "query",
}
_ENUM_SYNONYMS = {
    "ae": "Suspected Adverse Event", "adverse event": "Suspected Adverse Event",
    "pqc": "Product Quality Complaint", "quality complaint": "Product Quality Complaint",
    "review": "In Review", "in_review": "In Review", "inreview": "In Review",
    "close": "Closed", "closure": "Closed",
}


@dataclass
class ToolResult:
    ok: bool
    tool: str
    data: dict[str, Any] = field(default_factory=dict)
    code: str = ""
    message: str = ""
    issues: list[dict[str, str]] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)

    @property
    def invalid_args(self) -> bool:
        return (not self.ok) and self.code in INVALID_ARG_CODES


def _norm_key(k: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(k).strip().lower())


def repair_args(tool: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Deterministic typo repair: key aliases/near-misses, enum case, id casing."""
    schema = SCHEMAS[tool]
    fields = set(schema.model_fields)
    repaired: dict[str, Any] = {}
    notes: list[str] = []
    for raw_key, value in args.items():
        key = _norm_key(raw_key)
        if key not in fields:
            target = ALIASES.get(key)
            if target not in fields:
                near = difflib.get_close_matches(key, sorted(fields), n=1, cutoff=0.8)
                target = near[0] if near else None
            key = target or raw_key  # unknown stays -> rejected by extra="forbid"
        if key != raw_key:
            notes.append(f"{raw_key} -> {key}")
        if key in repaired:
            continue  # first spelling wins; never silently overwrite
        repaired[key] = value

    def fix(key: str, fn: Callable[[str], str]) -> None:
        v = repaired.get(key)
        if isinstance(v, str):
            new = fn(v.strip())
            if new != v:
                notes.append(f"{key} value normalised")
            repaired[key] = new

    fix("batch_lot", lambda v: v.upper())
    fix("ref", lambda v: v.upper())
    for key, enum in (("report_type", ReportType), ("reporter_type", ReporterType)):
        values = {e.value.casefold(): e.value for e in enum}
        fix(key, lambda v, values=values: values.get(v.casefold(), _ENUM_SYNONYMS.get(v.casefold(), v)))
    fix("target_status", lambda v: {"in review": "In Review", "closed": "Closed"}.get(
        v.casefold(), _ENUM_SYNONYMS.get(v.casefold(), v)))
    return repaired, notes


class ToolRuntime:
    """Validates every call against its schema, then runs the handler."""

    def __init__(
        self,
        db: Database,
        retriever_factory: Callable[[], HybridRetriever],
        llm_client: Optional[LLMClient] = None,
        allow_external: bool = False,
    ):
        self.db = db
        self.retriever_factory = retriever_factory
        self.llm_client = llm_client
        self.allow_external = allow_external
        self._handlers: dict[str, Callable[[Any], ToolResult]] = {
            "submit_intake_report": self._submit,
            "update_status": self._update_status,
            "rag_lookup": self._rag,
        }

    def execute(self, name: str, args: Any) -> ToolResult:
        if name not in SCHEMAS:
            return ToolResult(False, name, code="UNKNOWN_TOOL",
                              message=f"Unknown tool '{name}'. Available: {sorted(SCHEMAS)}.")
        if not isinstance(args, dict):
            return ToolResult(False, name, code="VALIDATION_ERROR",
                              message="Tool arguments must be a JSON object.")
        fixed, notes = repair_args(name, args)
        try:
            parsed = SCHEMAS[name].model_validate(fixed)
        except ValidationError as exc:
            issues = [{"field": ".".join(map(str, e["loc"])) or "arguments", "message": e["msg"]}
                      for e in exc.errors()]
            return ToolResult(False, name, code="VALIDATION_ERROR", issues=issues, repairs=notes,
                              message="Arguments failed validation: "
                              + "; ".join(f"{i['field']}: {i['message']}" for i in issues))
        result = self._handlers[name](parsed)
        result.repairs = notes
        return result

    # ---- handlers
    def _submit(self, a: SubmitIntakeArgs) -> ToolResult:
        outcome = validate_intake(
            report_type=a.report_type.value, product_name=a.product_name,
            batch_lot=a.batch_lot, date_received=a.date_received,
            reporter_type=a.reporter_type.value, description=a.description,
            event_description=a.event_description or "", onset_date=a.onset_date,
        )
        if not outcome.ok:
            return ToolResult(False, "submit_intake_report", code="DOMAIN_VALIDATION",
                              issues=[{"field": "report", "message": m} for m in outcome.errors],
                              message="; ".join(outcome.errors))
        ref = self.db.create_report(outcome.report)
        return ToolResult(True, "submit_intake_report", {"ref": ref, "status": "New"},
                          message=f"Report saved as {ref}.")

    def _update_status(self, a: UpdateStatusArgs) -> ToolResult:
        r = workflow.request_status_change(self.db, a.ref, a.target_status)
        data = {"ref": a.ref, "status": r.status, "pending_approval": r.pending_approval}
        if not r.ok:
            return ToolResult(False, "update_status", data, code="WORKFLOW_REJECTED", message=r.message)
        return ToolResult(True, "update_status", data, message=r.message)

    def _rag(self, a: RagLookupArgs) -> ToolResult:
        retrieval = self.retriever_factory().retrieve(a.query)

        def log_call(model: str, n: int) -> None:
            safe_model = re.sub(r"[^A-Za-z0-9._/\-]", "", model)[:40] or "unknown"
            self.db.log_audit("LLM_CALL", detail=f"{safe_model} chunks {n}")

        answer = generate_answer(a.query, retrieval.selected, self.llm_client,
                                 allow_external=self.allow_external, on_external_call=log_call)
        return ToolResult(True, "rag_lookup", {"answer": answer, "retrieval": retrieval},
                          message=answer.text)
