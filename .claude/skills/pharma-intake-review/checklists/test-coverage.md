# Test Coverage Checklist

- [ ] T1. Schema validation: regex, enums, missing fields, unknown fields, whitespace-only text.
- [ ] T2. Validation messages and PII heuristics, including false-positive guards (lot numbers, dates).
- [ ] T3. Storage: round trip, REF uniqueness/year reset, atomic rollback, status constraint, audit immutability.
- [ ] T4. Workflow: legal and illegal transitions, HITL freeze, reject/re-request, invalid reviewer input, DB-trigger bypass attempts.
- [ ] T5. Each RAG stage separately: BM25 (exact lot, length normalisation, formula), dense (synonym), RRF (formula), rerank (range, threshold).
- [ ] T6. Pipeline: selection limits, threshold, empty corpus, irrelevant query.
- [ ] T7. Generation guardrails: no-source skips LLM, toggle off, PII block, uncited/out-of-scope output, LLM error, mocked OpenRouter HTTP.
- [ ] T8. Router cases incl. refusal priority; tool auto-repair; circuit breaker trip/reset/not-tripped cases.
- [ ] T9. UI smoke tests (AppTest) for intake, dashboard lifecycle, Ask tab.
- [ ] T10. Tests never touch the network or the real DB (conftest strips key; temp DBs).
- [ ] T11. Hook payload exclusion is tested (currently verify whether a pytest exists for `audit_edit.py`).
- [ ] T12. Full suite passes: `python -m pytest`.

Suggested checks: `python -m pytest`, `grep -rn "def test_" tests | wc -l`, look for modules in `src/` with no matching test.
