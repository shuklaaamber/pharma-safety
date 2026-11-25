"""Shared text processing: tokenizer and the retrieval synonym lexicon.

The lexicon maps lay/medical synonyms to a shared concept token so semantic
stages can match "difficulty breathing" with "dyspnea". It is a RETRIEVAL aid
only; it encodes no clinical judgment.
"""
from __future__ import annotations

import re

# Keeps identifiers such as LOT-88392 / REF-2026-0001 as single tokens.
_TOKEN_RE = re.compile(r"[a-z]+(?:-\d+)+|[a-z0-9]+")

STOPWORDS = frozenset(
    "a an and are as at be by for from has have how in is it its of on or that the "
    "this to was were what when where which who why with do does did about any".split()
)

CONCEPTS: dict[str, tuple[str, ...]] = {
    "c_respiratory_distress": (
        "dyspnea", "dyspnoea", "difficulty breathing", "shortness of breath",
        "breathlessness", "trouble breathing", "hard to breathe",
    ),
    "c_severe_allergy": (
        "anaphylaxis", "anaphylactic", "severe allergic reaction", "allergic shock",
    ),
    "c_urticaria": ("urticaria", "hives", "itchy rash", "welts"),
    "c_nausea_vomiting": ("nausea", "vomiting", "queasy", "throwing up", "emesis"),
    "c_headache": ("headache", "migraine", "head pain"),
    "c_packaging_defect": (
        "torn blister", "damaged packaging", "broken seal", "seal broken",
        "cracked bottle", "leaking", "leak",
    ),
    "c_discoloration": (
        "discoloration", "discolouration", "discolored", "discoloured",
        "color change", "colour change",
    ),
    "c_tablet_defect": ("broken tablet", "crumbled", "chipped tablet", "chipped"),
}


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


_SUFFIXES = ("ations", "ation", "ings", "ing", "ied", "ies", "ed", "es", "al", "e")


def stem(tok: str) -> str:
    """Very light suffix stripping (approves/approval/approve -> approv).

    Identifiers and anything containing digits are left untouched.
    """
    if any(c.isdigit() for c in tok) or "-" in tok:
        return tok
    if tok.endswith("s") and not tok.endswith("ss") and len(tok) > 4:
        tok = tok[:-1]
    for suf in _SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def analyze(text: str, *, query: bool = False) -> list[str]:
    """Tokens plus concept tokens for any lexicon phrase present.

    For queries, the words of a matched phrase are replaced by its concept token so
    that a synonym match counts as full coverage of that phrase.
    """
    tokens = tokenize(text)
    out_concepts: list[str] = []
    consumed: set[int] = set()
    for concept, phrases in CONCEPTS.items():
        for phrase in phrases:
            ptoks = tokenize(phrase)
            n = len(ptoks)
            for i in range(len(tokens) - n + 1):
                if tokens[i : i + n] == ptoks:
                    if concept not in out_concepts:
                        out_concepts.append(concept)
                    consumed.update(range(i, i + n))
    if query:
        tokens = [t for i, t in enumerate(tokens) if i not in consumed]
    tokens = [stem(t) for t in tokens if t not in STOPWORDS]
    return tokens + out_concepts
