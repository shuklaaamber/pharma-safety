"""Answer generation with strict grounding guardrails.

The LLM sees ONLY the selected chunks and the query. Any problem (no key, opt-out,
PII in the outbound text, network error, uncited or out-of-scope output) falls
back to deterministic extractive quoting, so an answer is never ungrounded.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

import httpx

from .. import config
from ..validation import find_pii
from .pipeline import ScoredChunk
from .text import analyze

SYSTEM_PROMPT = (
    "You answer questions for pharmaceutical safety intake staff using ONLY the numbered "
    "sources provided. Rules: (1) Every sentence must end with a citation like [S1]. "
    "(2) Use only facts stated in the sources. (3) NEVER assess causality, recommend "
    "medical treatment, or state whether anything is regulatory reportable. "
    "(4) If the sources do not answer the question, reply exactly: NOT_FOUND. "
    "All data is fictional training data."
)

NO_SOURCE_TEXT = "No sufficiently relevant source found."
_CITE_RE = re.compile(r"\[S(\d+)\]")
_REGULATOR = r"(?:fda|ema|mhra|pmda|health canada|regulator\w*|authorit(?:y|ies)|health agency)"
_SCOPE_RE = re.compile(
    r"\bcaus(?:e|es|ed|ing|al|ality)\b|\b(?:likely|probably|possibly) related\b"
    r"|\brelated to (?:the )?(?:drug|product|medication)\b|\breportab\w*"
    r"|\b(?:should|must) be reported\b|\btreat(?:ment|ed|ing)?\b|\bprescrib\w*"
    r"|\bdos(?:e|age)\b"
    r"|\bside[- ]effects?\b|\bresponsible for\b|\bresult(?:s|ed)? (?:of|from)\b"
    r"|\bbecause of\b|\breaction to\b|\battributable to\b"
    rf"|\b(?:submit\w*|file[sd]?|notif\w+|report(?:ed|s)?)\b.{{0,60}}\b{_REGULATOR}\b"
    rf"|\b{_REGULATOR}\b.{{0,60}}\b(?:within|deadline|submit\w*|notif\w+)\b"
    r"|\b(?:take|give|administer)\b.{0,30}\b(?:tablets?|pills?|capsules?|mg|ibuprofen|aspirin|"
    r"paracetamol|acetaminophen)\b|\b\d+\s?mg\b",
    re.IGNORECASE,
)


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> str: ...


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        http: Optional[httpx.Client] = None,
    ):
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self._http = http

    def complete(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": 600,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        client = self._http or httpx.Client(timeout=self.timeout)
        try:
            resp = client.post(config.OPENROUTER_URL, json=payload, headers=headers)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            # Never include headers/key in the message.
            raise LLMError(f"LLM request failed: {type(exc).__name__}") from None
        finally:
            if self._http is None:
                client.close()
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM request failed: empty or non-text reply")
        return content


def default_client() -> Optional[OpenRouterClient]:
    key, model = config.openrouter_settings()
    return OpenRouterClient(key, model) if key else None


@dataclass
class Answer:
    text: str
    mode: str  # "llm" | "extractive" | "no_source"
    citations: list[tuple[str, str]] = field(default_factory=list)  # (label, source)
    reason: str = ""
    external_call: bool = False


def _excerpt(text: str, query: str, limit: int = 320) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    q = set(analyze(query, query=True))
    best = max(sentences or [text], key=lambda s: len(q & set(analyze(s))))
    return best if len(best) <= limit else best[: limit - 1].rstrip() + "…"


def extractive_answer(query: str, chunks: list[ScoredChunk], reason: str = "") -> Answer:
    lines = [
        f"- [S{i}] ({sc.chunk.source}) {_excerpt(sc.chunk.text, query)}"
        for i, sc in enumerate(chunks, 1)
    ]
    return Answer(
        "Relevant source excerpts:\n" + "\n".join(lines),
        "extractive",
        [(f"S{i}", sc.chunk.source) for i, sc in enumerate(chunks, 1)],
        reason,
    )


def check_grounding(text: str, n_sources: int) -> Optional[str]:
    """Return a failure reason, or None if the answer is cited and in scope."""
    if _SCOPE_RE.search(text):
        return "answer contained out-of-scope language"
    sentences = [
        re.sub(r"^[\-\*\d.\s]+", "", s).strip()
        for s in re.split(r"(?<=[.!?])\s+|\n+", text)
    ]
    for s in (s for s in sentences if len(s.split()) >= 3):
        cites = [int(c) for c in _CITE_RE.findall(s)]
        if not cites or any(not 1 <= c <= n_sources for c in cites):
            return "answer contained an uncited or invalidly cited sentence"
    return None


def generate_answer(
    query: str,
    selected: list[ScoredChunk],
    client: Optional[LLMClient] = None,
    *,
    allow_external: bool = False,
    on_external_call: Optional[Callable[[str, int], None]] = None,
) -> Answer:
    if not selected:
        return Answer(NO_SOURCE_TEXT, "no_source", reason="no chunk met the relevance threshold")
    if not allow_external:
        return extractive_answer(query, selected, "external LLM call not enabled")
    if client is None:
        return extractive_answer(query, selected, "no OpenRouter key configured")
    outbound = [query] + [sc.chunk.text for sc in selected]
    if any(find_pii(t) for t in outbound):
        return extractive_answer(query, selected, "blocked: possible personal data in outbound text")

    sources = "\n\n".join(f"[S{i}] ({sc.chunk.source})\n{sc.chunk.text}" for i, sc in enumerate(selected, 1))
    user = f"Sources:\n{sources}\n\nQuestion: {query}"
    if on_external_call:
        try:
            on_external_call(client.model, len(selected))
        except (ValueError, sqlite3.Error) as exc:  # fail closed: no audit, no outbound call
            return extractive_answer(query, selected, f"blocked: outbound call could not be audited ({type(exc).__name__})")
    try:
        reply = client.complete(SYSTEM_PROMPT, user)
    except LLMError as exc:
        return extractive_answer(query, selected, str(exc))
    if not isinstance(reply, str) or not reply.strip():  # also guards non-httpx clients
        return extractive_answer(query, selected, "LLM request failed: empty or non-text reply")
    text = reply.strip()

    if text.upper().startswith("NOT_FOUND"):
        return Answer(NO_SOURCE_TEXT, "no_source", reason="model found no answer in sources", external_call=True)
    problem = check_grounding(text, len(selected))
    if problem:
        ans = extractive_answer(query, selected, f"LLM output rejected: {problem}")
        ans.external_call = True
        return ans
    return Answer(
        text, "llm", [(f"S{i}", sc.chunk.source) for i, sc in enumerate(selected, 1)], external_call=True
    )
