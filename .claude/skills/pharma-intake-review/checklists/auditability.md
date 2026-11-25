# Auditability Checklist

- [ ] A1. Report creation writes `REPORT_CREATED` in the same transaction as the insert.
- [ ] A2. Every status change writes an audit row (`STATUS_CHANGED`, `CLOSURE_REQUESTED`, `CLOSURE_APPROVED`, `CLOSURE_REJECTED`).
- [ ] A3. `audit_log` is append-only at the DB level (UPDATE/DELETE triggers) and no code path attempts to edit or delete rows.
- [ ] A4. In Review -> Closed cannot happen without a recorded human decision (workflow code + `reports_status_guard` trigger); approval decisions are final.
- [ ] A5. No agent tool can approve a closure (HITL by construction).
- [ ] A6. External LLM calls (`LLM_CALL`) and circuit-breaker trips (`CIRCUIT_BREAKER_TRIPPED`) are audited.
- [ ] A7. Audit rows carry UTC timestamp, action, reference, controlled detail, and actor.
- [ ] A8. The PostToolUse hook is registered in `.claude/settings.json`, deterministic, and `logs/edit_audit.jsonl` shows entries for edits.
- [ ] A9. Audit viewer is read-only.
- [ ] A10. Known gaps are documented (e.g. DB file is not tamper-evident against a privileged user; no requester/approver separation).

Suggested checks: read `db.SCHEMA`, `audit.py`, `workflow.py`; inspect `.claude/settings.json` and `logs/edit_audit.jsonl`.
