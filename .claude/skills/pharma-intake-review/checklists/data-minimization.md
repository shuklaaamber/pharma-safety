# Data Minimization Checklist

- [ ] D1. No patient-identifier fields exist in schemas, DB tables, forms or tool args (models use `extra="forbid"`).
- [ ] D2. Free-text inputs (description, event description, product name, reviewer rationale, chat tool args) are PII-scanned before storage.
- [ ] D3. `audit_log` stores action, timestamp, reference, controlled `detail` and actor only; never descriptions, rationale or query text.
- [ ] D4. Reviewer identity is pseudonymous (`REV-###`), not a name.
- [ ] D5. The edit-audit hook (`.claude/hooks/audit_edit.py`) records only timestamp, tool name and file path; never `tool_input` content.
- [ ] D6. Outbound LLM calls: opt-in, PII-scanned query and chunks, only query + selected chunks sent, audit stores model + chunk count only.
- [ ] D7. Secrets (`OPENROUTER_API_KEY`) live only in gitignored `.env` / environment; not in source, tests, docs, logs or error messages.
- [ ] D8. Only synthetic data in fixtures, SOPs, demo data and docs.
- [ ] D9. Streamlit binds to localhost only; telemetry disabled.
- [ ] D10. No logging/printing of free-text user content.

Suggested checks: `grep -rn "api_key\|sk-or" --include=* .` (excluding `.env`), `grep -rn "print(\|logging" src`, inspect `.gitignore`, inspect `.streamlit/config.toml`.
