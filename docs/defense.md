# Defense — Pharma Safety Intake & Triage Tracker

A local training prototype using **synthetic data only**. It never assesses causality, recommends treatment, determines reportability, or replaces a pharmacovigilance system. Evidence: `docs/plan-approved.md`, `docs/review-evidence.md`, `docs/demo-walkthrough.md`, `logs/edit_audit.jsonl`, `.claude/settings.json`.

## 1. CLAUDE.md versus skills

`CLAUDE.md` is the always-on contract. It is loaded into every session, so it holds the rules that must never be forgotten: scope limits, synthetic-data rules, architecture constraints, RAG parameters and testing conventions. It is deliberately short.

The `pharma-intake-review` skill holds the long, task-specific checklists (data minimization, error handling, auditability, test coverage). They are only useful when reviewing, so they load on demand and don't consume context the rest of the time. The split is: **what must always hold goes in CLAUDE.md; how to check it goes in a skill.**

Honest note on evidence: the skill was created in the same session, so the Skill tool could not load it (skills load at session start). A subagent was told to follow `SKILL.md` and the checklists step by step. That shows the procedure works, but it is not a formal `/pharma-intake-review` invocation. Running the real command after a restart and appending the output to `docs/review-evidence.md` is still worth doing.

## 2. How Plan Mode helped

Planning before code settled questions that would otherwise have surfaced as rework:

- **Data flow:** form → `validate_intake` (collect all errors and PII hits first) → strict `IntakeReport` → one `BEGIN IMMEDIATE` transaction that allocates the REF, inserts the report and writes the audit row, so a failure rolls back all three.
- **Validation edge cases:** context-sensitive rules (AE-only fields, onset ≤ received ≤ today), `LOT-\d{5}`, and which fields get PII scans.
- **The one external call:** the case study says "no external APIs". Planning forced an explicit, documented exception (OpenRouter, generation step only) with mitigations: opt-in, PII pre-scan, minimal payload, metadata-only audit, extractive fallback.
- **HITL design:** deciding early that no agent tool can approve closure, and that the database enforces the same rule a second time.

## 3. Why hooks are deterministic

A PostToolUse hook is run by the harness, not by the model. After each `Edit|Write|MultiEdit` the harness executes `audit_edit.py`, which appends `{ts_utc, tool_name, file_path}` to `logs/edit_audit.jsonl`. The model cannot skip it, reword it or decide it is unnecessary, and the script never reads `tool_input` content, so file text cannot leak into the log. `tests/test_audit_edit_hook.py` checks payload exclusion and registration.

Limits (see section 6): the matcher does not cover NotebookEdit or file writes made through Bash, and the log is a plain editable file, so it is a **change record, not tamper-evident evidence**.

## 4. RAG reduces hallucination; it does not eliminate it

Retrieval grounds answers in SOP text and saved reports, but a model can still misread or overstate a source. The enforcing controls are mechanical and sit outside the model:

- **Relevance threshold (0.40):** if no chunk qualifies, the LLM is skipped and the answer is "No sufficiently relevant source found".
- **Citation check:** an LLM answer is accepted only if every sentence carries a valid `[Sn]` and none contains causality, treatment or reportability wording. Otherwise the app falls back to extractive quoting of the chunks.
- **Fallbacks:** toggle off, missing key, PII in outbound text, audit failure or LLM error all produce extractive output.

Residual risk: the scope check is regex-based and cannot be exhaustive, so it can both miss phrasings and over-refuse. A cited sentence can also be a poor paraphrase of its source. Human reading of the cited excerpt remains the final control.

## 5. What production would need

- Authentication and role-based access control; real reviewer identity.
- Encrypted database; backups and retention policy.
- Tamper-evident audit (hash chain or WORM storage), replacing the plain log and SQLite triggers.
- Computer system validation and 21 CFR Part 11 compliance (electronic records and signatures).
- Integration with a real pharmacovigilance system, which stays the system of record.
- Vendor and data-processing review of the external LLM provider, or an approved private endpoint.
- Secrets management, monitoring and alerting, penetration testing.

## 6. Known limitations and residual risks

These come from the review (`docs/review-evidence.md`) and are accepted for a local synthetic-data prototype. This section closes finding **A10**.

| Limitation | Why it matters | Current mitigation |
|---|---|---|
| **Reviewer identity is self-asserted.** Any user can type a `REV-###` ID and a role. | The approval record shows who claimed to approve, not who did. | IDs are pseudonymous by design (no names). Production needs authentication. |
| **No requester/approver separation.** The person who requests closure can also approve it. | Four-eyes control is absent. | None; flagged for production RBAC. |
| **Anyone with write access to the DB file can forge an approval.** They can `DROP TRIGGER` and edit tables directly. | The HITL gate and append-only audit are enforced by triggers inside the file they protect. | Triggers block ordinary SQL (forged approvals, non-New inserts, audit UPDATE/DELETE). The file is trusted and the app binds to 127.0.0.1. |
| **Hook log is editable, and hook coverage is partial.** NotebookEdit and Bash-driven writes are not matched. | The edit trail can be incomplete or altered. | Hook stores no content; tests check payload exclusion. Treat as a change record, not forensic evidence. |
| **Scope and PII checks are heuristics.** | A bare name with no cue word (e.g. "Jane Doe felt dizzy") is not detected; some out-of-scope phrasings may slip through, and benign ones may be refused. | Layered checks (router, grounding check, PII scan on input and outbound text); the limit is pinned by `test_known_limit_bare_names_are_not_detected`. Synthetic data only. |
| **Extractive answers apply no scope filter.** They quote SOP text as written. | Quoted SOP text could be read as advice if it were not synthetic. | SOPs are authored to disclaim scope. |
| **Polite status requests are read-only.** "Can you move REF-… to In Review?" does nothing. | Usability. | Deliberate: only imperative commands change status; rephrase to act. |
| **`data/intake.db` holds one `LLM_CALL` row from a manual live check.** | Cosmetic. | The audit log is append-only by design; the file is gitignored. |
| **External LLM call is a documented exception** to "no external APIs". | Query text and retrieved excerpts leave the machine when enabled. | Opt-in, PII-scanned, minimal, audited as metadata, extractive fallback. |
| **One test was flaky once** (since fixed). `test_ask_sop_question_is_extractive_when_toggle_off` timed out on a cold first run because the Ask-tab click builds the RAG index within Streamlit AppTest's 3 s default. | Slow-machine flake. | Click-triggered runs in the two Ask tests now use `timeout=30`; the full suite passed 4 consecutive runs afterward. |

Not verified: commit contents (the folder is not a git repo), live OpenRouter response shapes, browser rendering, and the optional sentence-transformers/CrossEncoder drop-ins.
