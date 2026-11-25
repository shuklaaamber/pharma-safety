# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Pharma Safety Intake & Triage Tracker

Persistent contract for AI coding agents working in this repo. Detailed review checklists live in `.claude/skills/pharma-intake-review/`, not here. The approved plan is `docs/plan-approved.md`.

## Commands
- Install: `python -m pip install -r requirements.txt`
- Run app: `streamlit run app.py` (bound to 127.0.0.1 via `.streamlit/config.toml`; keep it local)
- All tests: `python -m pytest`
- Single test: `python -m pytest tests/test_config.py::test_lot_pattern`
- `pyproject.toml` sets `pythonpath = ["src"]`; `app.py` adds `src/` to `sys.path` itself.

## Architecture (as built; see `docs/plan-approved.md` for the full target)
- `app.py` is only a Streamlit shell (tabs + synthetic-data banner). UI code lives in `src/pharma_intake/ui/`; domain logic must stay out of it.
- Data flow for intake: form widgets → `validation.validate_intake()` (collects all context-sensitive errors + PII heuristics first, then `build_report()` converts raw strings to the strict `models.IntakeReport`) → `db.Database.create_report()`, which in ONE `BEGIN IMMEDIATE` transaction allocates the REF (`ids.next_reference`), inserts the report and writes the audit row; any failure rolls all three back.
- `audit_log` is append-only via SQLite triggers; `audit.log_event` only accepts short controlled-vocabulary `detail` text, never descriptions. Tests point the UI at a temp DB with `monkeypatch.setattr(config, "DB_PATH", ...)` (or env `PHARMA_DB_PATH` for a real run).
- Model details:  Models use `strict=True, extra="forbid"`, so strings are NOT coerced to enums or dates: callers must construct `ReportType`/`ReporterType`/`date` values explicitly. `extra="forbid"` is also what keeps patient-identifier fields out; do not relax it.
- `config.py` is the single source for formats, statuses and RAG/circuit-breaker parameters; tests assert these match the spec, so change them only with the spec.
- Status lifecycle (`workflow.py`): New → In Review is direct. In Review → Closed is never one step: `request_status_change` only inserts a Pending row in `approvals` (report stays In Review, "frozen"); `decide_closure` records the reviewer (pseudonymous `REV-###` ID, role, rationale) and only then closes. The same rule is enforced a second time by SQLite triggers (`reports_status_guard`, plus `approvals_insert_pending`, `approvals_decision_complete`, `reports_insert_new`), so ordinary direct SQL cannot forge an approval or close a report. A user with write access to the DB file can still `DROP TRIGGER`; the DB file is trusted for this prototype (see `docs/review-evidence.md`). Reviewer rationale lives in `approvals`, never in `audit_log`. Dashboard actions use `st.session_state["flash"]` + `st.rerun()` so the table refreshes after a change.
- RAG (`rag/`): corpus = `data/sops/*.md` + saved reports → `chunker` (512/64 word-token windows) → `HybridRetriever` in `pipeline.py`: BM25 (`bm25.py`, exact tokens, identifiers like `LOT-88392` stay one token) + bi-encoder (`dense.py`, offline `LsaEncoder` = TF-IDF+SVD with the synonym/concept lexicon in `text.py`) → RRF (`rrf.py`) → reranker (`rerank.py`, offline `JointOverlapReranker`, scores in [0,1]) → keep ≥0.40, max 5. `Encoder`/`Reranker` are protocols; sentence-transformers/CrossEncoder drop-ins exist but are optional and untested here. Light stemming applies only in `analyze()` (dense/rerank), never to BM25 or to tokens with digits/hyphens.
- Generation (`rag/generator.py`): the only external call (OpenRouter). Flow: no selected chunks → "No sufficiently relevant source found" (LLM skipped); toggle off / no key / PII in outbound text / `LLMError` → extractive quoting; LLM output is accepted only if every sentence has a valid `[Sn]` citation and no causality/treatment/reportability wording, else extractive fallback. The key lives in gitignored `.env` (loaded by `config.load_dotenv`, read via `config.openrouter_settings()`); `tests/conftest.py` strips it so tests can never reach the network. Outbound calls are audited as `LLM_CALL` (model + chunk count only).
- Agent control plane (`agent/`), entered via `AgentOrchestrator.handle(message)` from the Ask tab: `router.route()` (pure regex rules, runs before anything else; priority refuse > greeting > status > intake > RAG default) → `ToolRuntime.execute()` (`tools.py`: alias/typo/case auto-repair, then strict Pydantic schemas, then domain validation) wrapped by `AgentOrchestrator.call_tool()`, which owns the `CircuitBreaker` (trips on the 3rd consecutive identical *invalid-argument* call; business rejections like illegal transitions do not count; trip is audited and halts ALL tools until `reset_breaker()`). Always send tool calls through `call_tool`, never `runtime.execute` directly, or the breaker is bypassed.
- HITL by construction: no agent tool can approve a closure. `update_status(..., "Closed")` only files the request (`PENDING_APPROVAL`); the decision exists solely as `workflow.decide_closure`, called from the dashboard form. Do not add an agent tool for it.
- Memory: `ShortTermMemory` = bounded in-process ReAct trace (not persisted); long-term = SQLite via `LongTermMemory`. Intake via chat uses `key=value; key=value` parsing (`router.parse_fields`), not free-text extraction. Chat only mutates status for imperative commands (`router.is_status_command`); questions mentioning a REF are read-only. User-derived text shown via markdown widgets must go through `ui/safe_text.escape_md`.
- Milestone progress: A–D, RAG, agent control plane and the review skill (`docs/review-evidence.md`, all findings fixed, A10 documented in `docs/defense.md`), `scripts/demo.py`, `docs/demo-walkthrough.md` and `docs/defense.md` done; final verification run (239 tests pass; live OpenRouter path not exercised). All plan phases complete.

## 1. Purpose
A local training prototype that captures product quality complaints and suspected adverse event reports, validates mandatory fields, tracks New → In Review → Closed, keeps an audit trail, and answers historical/SOP questions via hybrid RAG.

## 2. Scope boundaries (non-negotiable)
The application and any generated text MUST NEVER:
- assess causality between a product and an event;
- recommend medical treatment or advice;
- determine regulatory reportability or deadlines;
- replace or imply it replaces an enterprise pharmacovigilance system;
- make clinical or regulatory decisions.

Out-of-scope user asks get a fixed refusal message from the router. Do not weaken this to be "helpful".

## 3. Fictional-data rules
- Synthetic data only. No real patient names, initials, DOB, contact details, addresses, IDs, or medical history. The UI shows a synthetic-data banner.
- Forms must not contain patient-identifier fields. Free-text fields are scanned for PII-like patterns (emails, phones, name/DOB patterns) and rejected.
- Test fixtures and demo data use obviously fictional values (e.g. `LOT-12345`, product "Examplomab").
- Never log or audit free-text descriptions; audit stores actions, REF IDs, status values, timestamps only.

## 4. Architecture constraints
- Python 3.10+, Streamlit UI (thin; no business logic in `app.py`), Pydantic v2 strict models, SQLite via the stdlib `sqlite3` with parametrized SQL only.
- Local execution. The single permitted external call is OpenRouter for the RAG generation step, and it must be: opt-in (key + UI toggle), PII-scanned before sending, limited to the query plus retrieved chunks, audited as metadata, and with extractive fallback on any failure. No other network access.
- Secrets come from environment variables / gitignored `.env`; never hard-coded, logged, or committed.
- Audit log is append-only (DB triggers block UPDATE/DELETE).
- Status transitions are only New → In Review → Closed. In Review → Closed requires explicit human (HITL) approval recorded in the audit trail.
- Batch/lot format: `^LOT-\d{5}$`. Reference format: `REF-YYYY-XXXX`, unique.
- RAG parameters (single source in `config.py`): BM25 k1=1.3, b=0.75; chunks 512 tokens / 64 overlap; top-50 per retriever; RRF k=60; rerank threshold 0.40; pass top 3–5 chunks to generation.
- Circuit breaker: halt after more than 2 consecutive identical invalid tool calls.

## 5. Coding guidelines
- Type hints everywhere; small modules under `src/pharma_intake/`; no circular imports.
- Validate at boundaries (UI input, tool calls) with Pydantic; fail with explicit, field-specific, human-readable errors.
- No silent exception swallowing; return structured errors.
- Keep dependencies minimal; ask before adding any new one.
- Prefer protocols (`Encoder`, `Reranker`, `LLMClient`) so models can be swapped and faked in tests.

## 6. Testing conventions
- pytest; tests in `tests/` mirroring module names. Run `pytest -q` before declaring a milestone done.
- No network in tests: OpenRouter is tested with mocked HTTP or `FakeLLMClient`.
- Use temporary SQLite databases, never the real `data/` DB.
- Required coverage areas: schema validation, storage integrity and audit immutability, transitions and HITL freeze, circuit breaker, router, each RAG stage, generation guardrails, hook payload exclusion.

## 7. Workflow rules for agents
- Work milestone by milestone per `docs/plan-approved.md`; stop for user approval between phases.
- Do not expand scope beyond the plan or add features not requested.
- Never commit secrets, `.env`, the SQLite DB, or `logs/`.
- A PostToolUse hook logs file-edit events (tool name, path, timestamp only) to `logs/edit_audit.jsonl`; do not modify or bypass it.
