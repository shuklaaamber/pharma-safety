# Error Handling Checklist

- [ ] E1. Every mandatory field has an explicit, field-specific, context-sensitive message (AE vs quality complaint) and all errors are shown at once.
- [ ] E2. Cross-field rules are enforced (onset <= received, no future dates, AE requires extension, PQC rejects it).
- [ ] E3. Tool calls are validated by strict schemas (`batch_lot` regex, enums, `extra="forbid"`); failures return structured errors, not exceptions.
- [ ] E4. No bare `except:` and no silently swallowed exceptions; any `except Exception` is justified and reports the problem.
- [ ] E5. Transactions are atomic (REF allocation + insert + audit roll back together).
- [ ] E6. Illegal status transitions are rejected in code AND by the DB trigger; error messages explain the allowed order.
- [ ] E7. LLM failures (no key, timeout, HTTP error, malformed response) fall back to extractive output and never leak the key.
- [ ] E8. LLM output without valid `[Sn]` citations, or with causality/treatment/reportability wording, is rejected.
- [ ] E9. Circuit breaker counts only identical invalid-argument calls, trips on the 3rd, halts all tools, is audited, and is resettable.
- [ ] E10. Empty states are handled (no reports, empty corpus, empty query, no relevant source).

Suggested checks: `grep -rn "except" src`, read `db.create_report`, `workflow.py`, `generator.generate_answer`.
