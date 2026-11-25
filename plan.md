# Pharma Safety Intake & Triage Tracker — Implementation Plan

## Context
Greenfield capstone (workspace `c:\Pharma-Safety` is empty; Python 3.12, no packages installed). Build a local Streamlit app that captures synthetic safety/quality reports, enforces validation, tracks New → In Review → Closed with a HITL gate, keeps an audit trail, and answers historical/SOP queries via a 4-stage hybrid RAG pipeline plus an LLM generation step. It must never assess causality, treatment, or reportability.

**Decisions made with the user**
- Encoder/reranker: pluggable, offline default (optional sentence-transformers swap-in).
- Answers: LLM-generated via **OpenRouter**, grounded strictly on retrieved chunks.
- **Documented boundary deviation:** the case study says "no external APIs"; OpenRouter is the single explicit exception, limited to the generation step. Storage, BM25, embeddings, reranking and audit stay local. Mitigations are in Phase 6.

## Phase Roadmap (build order)

| # | Phase | Output | Exit gate |
|---|-------|--------|-----------|
| 0 | II – Plan approval | This plan copied to `docs/plan-approved.md` | User approves |
| 1 | I – Persistent guidance | `CLAUDE.md` | Reviewed by user |
| 2 | V (part 1) – Governance hook | `.claude/settings.json`, `audit_edit.py` | Test edit appears in log, no content |
| 3 | III-A – Skeleton | Folders, requirements, config, app boots | `streamlit run app.py` loads; `pytest` collects |
| 4 | III-B – Intake form & schemas | Pydantic models, form UI | Schema tests pass |
| 5 | III-C – Validation & persistence | validation, SQLite, REF IDs, audit | Storage/audit tests pass |
| 6 | III-D – Dashboard & lifecycle | Tracker, filters, transitions, HITL | Workflow tests pass |
| 7 | Adv. 5 – Hybrid RAG + LLM | 4-stage retrieval, generator | RAG tests pass |
| 8 | Adv. 6 – Agent control plane | Router, tools, memory, breaker, HITL | Control-plane tests pass |
| 9 | IV – Review skill | `pharma-intake-review` skill, invoked | Evidence in `docs/review-evidence.md` |
| 10 | Deliverables | Demo walkthrough, defense doc, final verification | All checks below green |

The hook is installed in step 2 (right after CLAUDE.md) so every later file edit is logged.

---

## Phase I — Persistent Guidance (`CLAUDE.md`)
Root contract covering: scope limits (no causality/treatment/reportability, synthetic data only, no real PII), architecture constraints (Streamlit + SQLite, local-first, single permitted external call = OpenRouter generation), coding guidelines (type hints, Pydantic v2 strict, parametrized SQL, thin UI), testing conventions (pytest, no network in tests, fake LLM client), and safe handling of fictional data. Detailed checklists go in the skill, not here.

## Phase II — Architectural Planning
This document. Copy to `docs/plan-approved.md` after approval, before any code.

### Target layout
```
CLAUDE.md
.claude/settings.json                 # PostToolUse hook
.claude/hooks/audit_edit.py           # logs ts, tool_name, file_path only
.claude/skills/pharma-intake-review/SKILL.md
.claude/skills/pharma-intake-review/checklists/{data-minimization,error-handling,auditability,test-coverage}.md
requirements.txt  pyproject.toml      # pytest config
app.py                                # Streamlit UI (thin)
src/pharma_intake/
  config.py       # DB path, k1=1.3, b=0.75, RRF k=60, top-50, threshold 0.40, chunk 512/64
  models.py       # Pydantic strict schemas, enums, LOT-\d{5}
  ids.py          # REF-YYYY-XXXX generator
  db.py           # SQLite schema + repository
  audit.py        # append-only audit (triggers block UPDATE/DELETE)
  validation.py   # context-sensitive errors, PII heuristics
  workflow.py     # transitions, HITL gate
  rag/{chunker,bm25,dense,rrf,rerank,generator,pipeline}.py
  agent/{router,tools,memory,circuit_breaker,orchestrator}.py
data/sops/*.md                        # synthetic SOPs; SQLite file also in data/ (gitignored)
scripts/demo.py
tests/
docs/{plan-approved,review-evidence,demo-walkthrough,defense}.md
logs/edit_audit.jsonl
```

## Phase V (part 1) — Governance Hook
- `.claude/settings.json`: PostToolUse, matcher `Edit|Write|MultiEdit`, command `python .claude/hooks/audit_edit.py`.
- Script reads stdin JSON, appends only `{ts_utc, tool_name, file_path}` to `logs/edit_audit.jsonl`. It never reads or writes `tool_input` content or descriptions.
- Proof: make a test edit, show the log line; unit test asserts no content fields.

## Phase III — Incremental Construction

### Milestone A — Skeleton
Folders, `requirements.txt` (streamlit, pydantic>=2, numpy, httpx, pytest), `config.py`, minimal `app.py` with tabs and a synthetic-data banner.

### Milestone B — Intake Form & Schemas
`models.py`: `IntakeReport` (category, product name, batch/lot, date received, reporter type, description) and `AEExtension` (event description, onset date). The form shows AE fields only when the category is Suspected Adverse Event. There are no patient-identifier fields.

### Milestone C — Validation & Persistence
- `validation.py`: field-specific errors (e.g. "Batch/lot is required; format LOT-12345"), onset ≤ received date, PII heuristics (emails, phones, name/DOB patterns).
- `db.py` / `ids.py`: SQLite repo, unique REF IDs, audit entry on create.
- `audit.py`: append-only, stores actions and timestamps, no free text.

### Milestone D — Dashboard & Workflow Lifecycle
- Tracker table with status and report-type filters.
- `workflow.py`: legal transitions only (New→In Review→Closed).
- HITL gate on In Review→Closed: reviewer ID + rationale required; state frozen until approval is recorded in the audit trail.
- Audit viewer tab.

## Advanced Topic — Hybrid RAG Pipeline (Phase 7)
1. **BM25** (own implementation, k1=1.3, b=0.75): tokenizer preserves `LOT-88392`-style tokens.
2. **Dense**: 512-token chunks / 64 overlap, `Encoder` protocol; default TF-IDF + truncated SVD (numpy) with a small synonym lexicon ("difficulty breathing"↔"dyspnea"); optional `SentenceTransformerEncoder`; cosine similarity.
3. **RRF**: top-50 from each, score = Σ 1/(60+rank).
4. **Rerank**: `Reranker` protocol; default joint lexical/semantic scorer normalized to [0,1]; drop <0.40; keep top 3–5; optional CrossEncoder swap-in.
5. **Generation** (`generator.py`): `LLMClient` protocol; default `OpenRouterClient` (HTTPS POST to `https://openrouter.ai/api/v1/chat/completions`, key/model from `OPENROUTER_API_KEY` / `OPENROUTER_MODEL`, temperature 0, timeout; key never hard-coded or logged; `.env` gitignored). Prompt gets only the top 3–5 chunks tagged `[S1]`…, with a fixed system prompt: answer only from context, cite `[Sn]`, never assess causality/treatment/reportability, say "not found" otherwise.
   - **Egress mitigations**: opt-in (needs a key and the sidebar toggle "Allow external LLM call"); only the query and selected chunks leave the machine; pre-send PII scan blocks the call and falls back to extractive; synthetic data only; outbound calls audited as metadata (model, chunk IDs, timestamp).
   - **Guardrails**: no chunk ≥0.40 → skip the LLM and return "No sufficiently relevant source found". Post-check requires a valid `[Sn]` on every sentence and scans for scope-violating language. Failures, network errors, timeouts or a missing key fall back to extractive quoting of the chunks.
6. **Corpus**: SOP markdown + saved reports (description fields only, synthetic). `FakeLLMClient` for tests.

## Advanced Topic — Agent Control Plane (Phase 8)
- **Step 1 `tools.py`**: `submit_intake_report`, `update_status`, `rag_lookup` validated via strict Pydantic; typo auto-repair (case, whitespace, known alias keys) else structured error.
- **Step 2 `memory.py`**: in-process ReAct trace (short-term); SQLite (long-term).
- **Step 3 `router.py`**: deterministic rules → greeting | rag | intake | status; fixed refusal for causality/treatment/reportability asks.
- **Step 4 HITL**: Closed request returns `PENDING_APPROVAL`; only an explicit approval call with reviewer ID completes it.
- **Step 5 `circuit_breaker.py`**: signature = tool name + canonical args hash; more than 2 consecutive invalid calls → halt and audit; reset on success or a different call.
- **UI**: tabs Intake · Dashboard · Ask (shows trace + citations) · Audit.

## Phase IV — Specialized Review Skill (Phase 9)
`.claude/skills/pharma-intake-review/SKILL.md` references four checklists: data minimization, error handling, auditability, test coverage. Invoke it on the finished code and save its output to `docs/review-evidence.md`.

## Phase V (part 2) — Governance Evidence
Include `logs/edit_audit.jsonl` and the settings file in the final package.

## Automated Tests (pytest)
- Schema validation (regex, enums, missing fields, PII rejection)
- REF ID uniqueness
- Storage round-trip; audit immutability (UPDATE/DELETE blocked)
- Transitions, illegal ones, HITL freeze
- Circuit breaker (3rd identical invalid call halts; reset)
- Router cases
- BM25 exact lot match; dense synonym match; RRF math; reranker threshold/top-k
- End-to-end RAG with `FakeLLMClient`: citation check, uncited/out-of-scope output → extractive fallback, no-context refusal skips LLM, LLM-down fallback, PII pre-send block
- OpenRouter client with mocked HTTP only (no network in tests)
- Hook script excludes content

## Deliverables (Phase 10)
- `docs/demo-walkthrough.md`, generated by `scripts/demo.py`: two fictional reports, one status transition with HITL, one RAG query, audit dump.
- `docs/defense.md` answering the 5 reflection questions:
  1. CLAUDE.md = always-on contract; skills = on-demand checklists.
  2. Plan Mode clarified data flow and validation edge cases.
  3. Hooks are deterministic because the harness executes them with no model judgment.
  4. RAG reduces but does not eliminate hallucination; threshold + citation checks + extractive fallback do the enforcing.
  5. Production needs: auth/RBAC, encrypted DB, tamper-evident audit (hash chain/WORM), CSV/21 CFR Part 11 validation, real PV-system integration, vendor/data-processing review of the external LLM provider (or an approved private endpoint), secrets management, monitoring, backups, pen testing.

## Verification
1. `pip install -r requirements.txt`; `pytest -q` all green.
2. `streamlit run app.py`: submit two fictional reports (one AE, one PQC); confirm validation errors on missing fields, REF IDs, dashboard filters.
3. Move a report New → In Review → attempt Closed → confirm frozen until reviewer approval; audit tab shows entries.
4. Requires `OPENROUTER_API_KEY` and internet, otherwise the extractive fallback shows. Ask "LOT-88392 anaphylaxis" and "difficulty breathing" → cited chunks; gibberish → refusal; causality question → scope refusal; 3 identical invalid tool calls → breaker halts.
5. Edit a file and confirm `logs/edit_audit.jsonl` has no content fields.
