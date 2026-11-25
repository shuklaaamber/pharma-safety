"""Step 3: deterministic semantic router (rules only; no model involved).

Runs BEFORE any tool or LLM. Priority: refuse out-of-scope > greeting > status
workflow > new intake > hybrid RAG (default for informational questions).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Route(str, Enum):
    DIRECT = "direct_response"
    RAG = "hybrid_rag"
    INTAKE = "intake_form_tool"
    STATUS = "status_workflow_manager"
    REFUSE = "out_of_scope"


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    rule: str


SCOPE_REFUSAL = (
    "I can't help with that. This tool does not assess causality, recommend medical "
    "treatment, or determine regulatory reportability; those decisions belong to qualified "
    "staff using the enterprise pharmacovigilance system."
)
GREETING_REPLY = (
    "Hello! I can search SOPs and past reports, help submit a new intake report, or move a "
    "report through its status workflow. All data here is fictional."
)

_AGENCY = r"(?:fda|ema|mhra|pmda|health canada|regulator\w*|authorit(?:y|ies)|health agency)"
_REFUSE = [
    ("causality", re.compile(
        r"\bcausality\b|\bcaused by\b"
        r"|\b(?:did|does|do|is|are|was|were|could|might|can|may)\b.{0,60}\b(?:cause[ds]?|causing|"
        r"related to|due to|linked to|responsible for|result of|resulting from|because of|"
        r"reaction to|attributable to|side[- ]effects?)\b", re.I)),
    ("treatment", re.compile(
        r"\b(?:what|which)\b.{0,30}\b(?:treatment|medication|dose|dosage)\b"
        r"|\bshould\b.{0,40}\b(?:take|stop|treat|use)\b|\bhow (?:to|do i|should i) treat\b"
        r"|\bprescri\w+|\bmedical advice\b"
        r"|\b(?:can|could|may|should|do|does)\b.{0,20}\b(?:i|we|he|she|they|patients?)\b.{0,20}"
        r"\b(?:give|take|use|administer|stop|combine)\b"
        r"|\bsafe to (?:take|use|give|combine|drink|mix)\b"
        r"|\b(?:give|administer|take)\b.{0,30}\b(?:ibuprofen|aspirin|paracetamol|acetaminophen|"
        r"antihistamines?|tablets?|pills?|capsules?)\b|\b\d+\s?mg\b", re.I)),
    ("reportability", re.compile(
        r"\breportab\w*|\bexpedited\b|\b15[- ]day\b"
        r"|\b(?:need|have|must|should|required|obliged)\b.{0,20}\b(?:report|submit|notify|file)\b.{0,40}"
        rf"\b{_AGENCY}\b"
        rf"|\b(?:submit|submitted|file|filed|notify|report)\b.{{0,40}}\b{_AGENCY}\b"
        rf"|\b{_AGENCY}\b.{{0,60}}\b(?:deadline|within|days?|submit\w*|file|filing|notify)\b"
        r"|\b(?:deadline|due date|time ?frame)\b.{0,40}\b(?:submit\w*|report\w*|fil(?:e|ing)|notif\w+)\b", re.I)),
]
_GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening)|thanks|thank you|bye)\b[\s!.,?]*$", re.I)
REF_RE = re.compile(r"REF-\d{4}-\d{4,}", re.I)
_STATUS_VERB = re.compile(
    r"\b(?:move|update|change|set|advance|mark|close|closure|review|status|promote)\b", re.I)
_INTAKE = re.compile(
    r"\b(?:submit|log|record|file|create|add|enter)\b.{0,30}\b(?:report|complaint|event|intake)\b"
    r"|\bnew (?:report|complaint|intake|adverse event)\b", re.I)


def route(message: str) -> RouteDecision:
    text = message or ""
    for name, pat in _REFUSE:
        if pat.search(text):
            return RouteDecision(Route.REFUSE, f"refuse:{name}")
    if _GREETING.match(text):
        return RouteDecision(Route.DIRECT, "greeting")
    if REF_RE.search(text) and _STATUS_VERB.search(text):
        return RouteDecision(Route.STATUS, "ref+status-verb")
    if _INTAKE.search(text):
        return RouteDecision(Route.INTAKE, "intake-phrase")
    return RouteDecision(Route.RAG, "default-informational")


_STATUS_COMMAND = re.compile(
    r"^\s*(?:(?:please|kindly)\s+)?(?:move|update|change|set|advance|mark|close|promote)\b", re.I)


def is_status_command(message: str) -> bool:
    """True only for imperative requests ("move REF-... to in review").

    Questions and statements that merely mention a REF and a status word are read-only.
    """
    return bool(_STATUS_COMMAND.match(message or ""))


def extract_ref(message: str) -> Optional[str]:
    m = REF_RE.search(message or "")
    return m.group(0).upper() if m else None


def extract_target_status(message: str) -> Optional[str]:
    t = (message or "").lower()
    if re.search(r"\bclos(?:e|ed|ure|ing)\b", t):
        return "Closed"
    if re.search(r"\bin[ _-]?review\b|\bto review\b|\breview\b", t):
        return "In Review"
    return None


_FIELD_RE = re.compile(r"(\w+)\s*=\s*(.+)$")


def parse_fields(message: str) -> dict[str, str]:
    """Parse `key=value; key=value` (or one per line) into raw tool arguments."""
    out: dict[str, str] = {}
    for seg in re.split(r"[;\n]", message or ""):
        m = _FIELD_RE.search(seg.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out
