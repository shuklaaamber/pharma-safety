"""Control plane: router -> (breaker-guarded) tools -> response, with ReAct trace."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ..db import Database
from ..rag.generator import LLMClient
from ..rag.pipeline import HybridRetriever
from .circuit_breaker import CircuitBreaker, call_signature
from .memory import LongTermMemory, ShortTermMemory
from .router import (
    GREETING_REPLY, SCOPE_REFUSAL, Route, extract_ref, extract_target_status, is_status_command,
    parse_fields, route,
)
from .tools import SCHEMAS, ToolResult, ToolRuntime

INTAKE_TEMPLATE = (
    "To submit a report, send fields as `key=value` separated by `;`, e.g.\n"
    "submit report: report_type=Product Quality Complaint; product_name=Examplomab; "
    "batch_lot=LOT-12345; date_received=2026-11-20; reporter_type=Consumer; "
    "description=Blister packaging was torn\n"
    "(Adverse events also need event_description and onset_date.) Fictional data only."
)
BREAKER_MESSAGE = (
    "Circuit breaker tripped: the same tool call failed validation more than 2 times in a "
    "row, so execution was halted. Fix the arguments and reset the breaker to continue."
)


@dataclass
class AgentResponse:
    route: Route
    text: str
    tool_result: Optional[ToolResult] = None
    halted: bool = False
    pending_approval: bool = False


class AgentOrchestrator:
    def __init__(
        self,
        db: Database,
        retriever_factory: Callable[[], HybridRetriever],
        llm_client: Optional[LLMClient] = None,
        allow_external: bool = False,
    ):
        self.db = db
        self.runtime = ToolRuntime(db, retriever_factory, llm_client, allow_external)
        self.breaker = CircuitBreaker()
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory(db)

    # -- guarded tool entry point (also usable directly by a tool-calling model)
    def call_tool(self, name: str, args: Any) -> ToolResult:
        if self.breaker.tripped:
            return ToolResult(False, name, code="CIRCUIT_OPEN", message=BREAKER_MESSAGE)
        result = self.runtime.execute(name, args)
        was_tripped = self.breaker.tripped
        self.breaker.record(call_signature(name, args), result.invalid_args)
        if self.breaker.tripped and not was_tripped:
            # Only a known tool name is audited; a caller-supplied string never is.
            tool = name if name in SCHEMAS else "UNKNOWN_TOOL"
            message = BREAKER_MESSAGE
            try:
                self.db.log_audit("CIRCUIT_BREAKER_TRIPPED", detail=tool)
            except (ValueError, sqlite3.Error) as exc:  # the trip must still halt execution
                message += f" (Audit write failed: {type(exc).__name__}.)"
            return ToolResult(False, name, code="CIRCUIT_OPEN", message=message,
                              issues=result.issues, repairs=result.repairs)
        return result

    def reset_breaker(self) -> None:
        self.breaker.reset()

    def _act(self, thought: str, name: str, args: Any) -> ToolResult:
        res = self.call_tool(name, args)
        self.short_term.add(thought, f"{name}", f"{'ok' if res.ok else res.code}: {res.message}")
        return res

    def handle(self, message: str) -> AgentResponse:
        d = route(message)
        thought = f"route={d.route.value} via {d.rule}"

        if d.route is Route.REFUSE:
            self.short_term.add(thought, "refuse", "fixed scope message")
            return AgentResponse(d.route, SCOPE_REFUSAL)
        if d.route is Route.DIRECT:
            self.short_term.add(thought, "direct_response", "greeting")
            return AgentResponse(d.route, GREETING_REPLY)

        if d.route is Route.STATUS:
            ref = extract_ref(message)
            target = extract_target_status(message) if is_status_command(message) else None
            if target is None:  # read-only: long-term memory lookup
                state = self.long_term.report_state(ref)
                self.short_term.add(thought, "long_term.report_state", str(state))
                if state is None:
                    return AgentResponse(d.route, f"Report {ref} was not found.")
                text = f"{ref}: status {state['status']}" + (
                    " (closure awaiting human approval)" if state["pending_approval"] else "")
                return AgentResponse(d.route, text, pending_approval=state["pending_approval"])
            res = self._act(thought, "update_status", {"ref": ref, "target_status": target})
            return self._status_response(d.route, res)

        if d.route is Route.INTAKE:
            fields = parse_fields(message)
            if not fields:
                self.short_term.add(thought, "intake_template", "no fields supplied")
                return AgentResponse(d.route, INTAKE_TEMPLATE)
            res = self._act(thought, "submit_intake_report", fields)
            return self._tool_response(d.route, res)

        res = self._act(thought, "rag_lookup", {"query": message.strip()})
        return self._tool_response(d.route, res)

    # -- response shaping
    def _status_response(self, r: Route, res: ToolResult) -> AgentResponse:
        if res.code == "CIRCUIT_OPEN":
            return AgentResponse(r, res.message, res, halted=True)
        pending = bool(res.data.get("pending_approval"))
        if res.ok and pending:
            text = ("PENDING_APPROVAL: closure requested. The report stays In Review until a "
                    "human reviewer records a decision in the Dashboard.")
        else:
            text = res.message
        return AgentResponse(r, text, res, pending_approval=pending)

    def _tool_response(self, r: Route, res: ToolResult) -> AgentResponse:
        if res.code == "CIRCUIT_OPEN":
            return AgentResponse(r, res.message, res, halted=True)
        if res.ok:
            return AgentResponse(r, res.message, res)
        detail = "\n".join(f"- {i['field']}: {i['message']}" for i in res.issues) or res.message
        fixed = f"\n(auto-repaired: {', '.join(res.repairs)})" if res.repairs else ""
        return AgentResponse(r, f"Tool call rejected ({res.code}):\n{detail}{fixed}", res)
