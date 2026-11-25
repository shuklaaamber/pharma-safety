# Review Evidence — `pharma-intake-review` skill

**How this was produced:** the skill (`.claude/skills/pharma-intake-review/SKILL.md` + 4 checklists) was created in the same session, so the `Skill` tool could not load it (skills load at session start). An independent subagent was therefore instructed to follow `SKILL.md` and the checklists step by step over the whole repo. This is evidence of the review procedure, not of a formal `/pharma-intake-review` invocation; run that after a session restart and append the output here.

**Status of findings:** reported by the reviewer, not yet independently re-run by the author. No code has been changed in response. See "Disposition" at the bottom.

---

## Review report (subagent output, key never printed)

**pytest:** 162 passed (113 `def test_` across 12 files).
**API key:** appears only in the gitignored `.env`; no `print(`/`logging` in `src` or `app.py`.
**Scope guardrail:** SOPs, banner and refusal text only disclaim causality/treatment/reportability; weaknesses are in enforcement (findings 4, 5).
**Not a git repo**, so what would be committed could not be checked.

### 1. Data minimization

| Item | Result | Evidence |
|---|---|---|
| D1 No patient-identifier fields | PASS | `models.py:33` `extra="forbid"`; `db.py:14-28`; `intake_form.py:21-37`; `tools.py:30` |
| D2 Free text PII-scanned | PASS, with gaps | `validation.py:131-140`; `tools.py:175`; `workflow.py:133`; heuristics gaps → finding 6 |
| D3 Audit holds no free text | **FAIL** | `audit.py:16,26` only checks charset/length; `ref`/`actor` unchecked; `orchestrator.py:62` writes caller-supplied tool name (finding 3) |
| D4 Reviewer ID pseudonymous | PASS | `workflow.py:21,125` `^REV-\d{3}$` |
| D5 Hook stores only ts/tool/path | PASS | `audit_edit.py:20-26`; every log line matches 3-key shape |
| D6 Outbound LLM opt-in/scanned/minimal/audited | PASS, caveat | `ask.py:30-37`, `generator.py:141-150`, `tools.py:200`; weak PII scan (6), `LLM_CALL` can fail/truncate (7) |
| D7 Secrets only in `.env` | PASS | `.gitignore:1`; `generator.py:77-79` error text uses exception type only |
| D8 Synthetic data only | PASS | SOPs/tests use `LOT-12345`/Examplomab |
| D9 Localhost, no telemetry | PASS | `.streamlit/config.toml` |
| D10 No logging of free text | PASS | no logging/print; in-memory trace ≤240 chars, never persisted |

### 2. Error handling

| Item | Result | Evidence |
|---|---|---|
| E1 Field-specific, context-sensitive, all at once | PASS | `validation.py:70-141` |
| E2 Cross-field rules | **FAIL (partial)** | PQC + AE fields returns `ok=True, ae=None` silently (finding 8); `test_pqc_ignores_ae_fields` enshrines it |
| E3 Strict tool schemas, structured errors | PASS | `tools.py:33-57,153-171` |
| E4 No bare/silent excepts | PASS | `tools.py:163`, `generator.py:77,155`, `validation.py:179`, `audit_edit.py:38` all report |
| E5 Atomic create | PASS | `db.py:95-117` |
| E6 Illegal transitions rejected in code and DB | PASS (normal path) | `workflow.py:77-107`, `db.py:48-55`; trigger bypassable by direct SQL (finding 2) |
| E7 LLM failures fall back | **FAIL (partial)** | null/non-string `content` → uncaught `AttributeError` at `generator.py:154` (finding 5) |
| E8 Uncited/out-of-scope output rejected | PASS, gaps | `generator.py:116-128`; `_SCOPE_RE` narrow (finding 4) |
| E9 Circuit breaker | PASS | `circuit_breaker.py:33-42`, `orchestrator.py:56-65`; trip audit can raise (finding 3) |
| E10 Empty states | PASS | `dashboard.py:44`, `audit_view.py:14`, `pipeline.py:76`, `generator.py:139`, `tools.py:50` |

### 3. Auditability

| Item | Result | Evidence |
|---|---|---|
| A1 `REPORT_CREATED` same txn | PASS | `db.py:117` |
| A2 Every status change audited | PASS | `workflow.py:81,94,153,157` |
| A3 Append-only at DB level | PASS | `db.py:68-71`, `42-46` |
| A4 No close without recorded human decision | **FAIL (hardening gap)** | trigger only checks an `Approved` row exists (`db.py:52-53`); verified bypass via raw SQL (finding 2) |
| A5 No agent tool can approve | PASS | `tools.py:53-57`; `decide_closure` only from `dashboard.py:87` |
| A6 `LLM_CALL` / breaker audited | PASS, caveat | `tools.py:200`, `orchestrator.py:62` (findings 3, 7) |
| A7 Rows carry ts/action/ref/detail/actor | PASS | `db.py:60-67`, `audit.py:28-37` |
| A8 Hook registered, deterministic, log populated | PASS, limits | `.claude/settings.json:3-13`; Bash/NotebookEdit edits not matched (finding 9) |
| A9 Audit viewer read-only | PASS | `audit_view.py` |
| A10 Known gaps documented | **FAIL (partial)** | forged-approval gap, self-asserted reviewer identity, no requester/approver separation undocumented; `docs/defense.md` not yet written |

### 4. Test coverage

| Item | Result | Evidence |
|---|---|---|
| T1 Schema | PASS | `test_models.py` |
| T2 Validation/PII/false positives | PASS | `test_validation.py` (no negative tests for PII gaps) |
| T3 Storage | PASS | `test_db.py` |
| T4 Workflow | PASS, gap | missing: forged-`Approved`-row bypass, direct INSERT of Closed report |
| T5 RAG stages | PASS | `test_rag_stages.py` |
| T6 Pipeline | PASS | `test_rag_pipeline.py` |
| T7 Generation guardrails | PASS, gap | missing: null/non-string content; scope-regex adversarial set |
| T8 Router/repair/breaker | PASS | router gaps in finding 4 untested |
| T9 UI smoke | PASS, gap | no test of Ask-tab status-mutation path |
| T10 No network / no real DB | PASS | `conftest.py:5-7`; note `data/intake.db` has 1 `LLM_CALL` row (06:53) from the manual live check, not from tests |
| T11 Hook payload exclusion tested | **FAIL** | no test references `audit_edit` |
| T12 Full suite | PASS | 162 passed |

### Findings (most severe first)

**2. Medium — HITL DB guard bypassable by direct SQL (`db.py:29-55`).** `reports_status_guard` accepts any `approvals` row with `decision='Approved'`; no INSERT trigger on `approvals`, decide-once trigger permits Pending→Approved with NULL reviewer/rationale, and `reports` has no INSERT guard. Verified: raw INSERT of an Approved row then `UPDATE reports SET status='Closed'` closed the report with no audit row. Requires DB-file access. CLAUDE.md states "direct SQL cannot bypass it", which overstates the guard. *Fix:* BEFORE INSERT on `approvals` aborting non-Pending; decide trigger requiring `REV-###` reviewer and non-empty rationale; BEFORE INSERT on `reports` requiring status `New`; soften CLAUDE.md wording; add tests.

**3. Medium — Audit can receive free text; trip audit can crash (`audit.py:16,26`; `orchestrator.py:62`).** `_DETAIL_RE` restricts charset/length only. `call_tool` is public, so a caller-supplied tool name such as "Jane Doe born 1980 headache" was stored in `audit_log.detail` (verified); a name with disallowed characters made the third call raise `ValueError` after the breaker had tripped. *Fix:* allow-list `detail`; write `name if name in SCHEMAS else "UNKNOWN_TOOL"`; validate `ref`/`actor`; make a failed audit write unable to mask the trip.

**4. Medium — Scope guardrails have verified holes.** Router did not refuse: "Is the rash a side effect of Examplomab?", "Could Examplomab be responsible for the nausea?", "What is the deadline to submit to the FDA?", "Do we have to file this with EMA within 15 days", "Can I give ibuprofen for the headache?", "Is it safe to take this with alcohol?". `check_grounding` accepted: "Serious events are submitted to the FDA within 15 days [S1].", "The rash is a side effect of the product [S1].", "Take two tablets with food [S1].", "Notify the regulator within 7 days [S1]." The extractive path applies no scope filter. *Fix:* widen both regexes, add an adversarial test set, consider deny-by-default filtering on the extractive path too.

**5. Medium-Low — Null/non-string LLM content crashes the Ask tab (`generator.py:76,154`).** A model reply with `content: null` makes `.strip()` raise `AttributeError` (not `LLMError`); verified with a fake client. `TypeError` from unexpected JSON shapes also uncaught; temporary `httpx.Client` never closed. *Fix:* require non-empty `str` else raise `LLMError`; catch `TypeError`/`AttributeError`; add test.

**6. Medium-Low — PII heuristics have verified gaps (`validation.py:19-34`).** Accepted: "my name is john smith", "Patient Smith reported", "patient: jane", "J.S. aged 54 male", "Jane Doe, 12 Oak, call 555-1234", "lives in Springfield, IL 62704", "SSN 123456789". Same scanner guards outbound LLM text. *Fix:* case-insensitive name tokens, initials/age heuristics, negative tests documenting limits.

**7. Low — `LLM_CALL` audit can truncate or abort the call (`tools.py:200`, `audit.py:16`, `generator.py:151-152`).** `[:60]` can drop the chunk count for long model names; a model string with characters outside the allowed set raises `ValueError` before the call, uncaught (verified). *Fix:* truncate the model only, sanitise it, and fall back to extractive output on audit failure.

**8. Low — PQC path silently drops AE fields (`validation.py:157-169`).** Verified `ok=True, ae=None` for a PQC given event description and onset date; no warning to the operator. *Fix:* emit an explicit message or relax the checklist wording; update `test_pqc_ignores_ae_fields`.

**9. Low — Hook coverage and test (`.claude/settings.json:5`).** Matcher `Edit|Write|MultiEdit` misses NotebookEdit and Bash-driven file writes; no test for payload exclusion (CLAUDE.md lists it as required). Log is plain and editable. *Fix:* add `tests/test_audit_edit_hook.py`; document limits.

**10. Low — Questions can trigger status changes (`router.py:54-86`, `orchestrator.py:86-97`).** Verified: "What is the status of REF-2026-0001 and does the SOP review period apply?" moved a New report to In Review. HITL still protects closure. *Fix:* require imperative form or treat questions as read-only.

**11. Low — Other.** `data/intake.db` holds an `LLM_CALL` row from manual testing; `.gitignore` misses `-journal/-wal/-shm`; user text rendered as Markdown (image links would make the browser fetch external URLs); `LOT_PATTERN` `\d` accepts non-ASCII digits (verified "LOT-１２３４５") — use `[0-9]`; no requester/approver separation, reviewer ID self-asserted (A10).

### Overall verdict
Conditional pass for a synthetic training prototype. Core controls work and are tested (strict models, atomic transaction, append-only audit, HITL workflow, breaker, key hygiene). Reviewer recommends fixing findings 4, 3 and 2, adding the hook test (9), and documenting known gaps (A10) before defense/demo.

### Not verified
Commit contents (no git repo); live OpenRouter response shapes; browser rendering; optional sentence-transformers/CrossEncoder drop-ins; origin of the `LLM_CALL` row; `scripts/demo.py`, `docs/demo-walkthrough.md`, `docs/defense.md` (not yet written).

---

## Disposition
Updated 2026-11-23 after the user approved fixing findings 2, 3, 4, 5 and 9. Second pass the same day fixed the small findings. Full suite: **239 passed** (was 162). New regression tests: `tests/test_review_hardening.py`, `tests/test_audit_edit_hook.py`, `tests/test_small_fixes.py`. Each finding below was re-checked by the author against the adversarial inputs listed in the report, not just by the subagent.

| Finding | Status | What changed |
|---|---|---|
| 2 HITL DB guard | **Fixed** | New triggers: `approvals_insert_pending` (approvals open only as Pending, only on an In Review report), `approvals_decision_complete` (decision needs `REV-###` reviewer, non-empty rationale, timestamp; ref/requested_at frozen), `reports_insert_new`. CLAUDE.md wording softened. **Residual:** anyone with write access to the DB file can `DROP TRIGGER`; the file is trusted. |
| 3 Audit free text / trip crash | **Fixed** | `audit.log_event` allow-lists `action`, validates `ref` and `actor`. Breaker trip audits `name` only if it is a known tool, else `UNKNOWN_TOOL`; a failed audit write is appended to the message and cannot mask the trip. |
| 4 Scope holes | **Fixed (heuristic)** | Router and `_SCOPE_RE` widened; all six router phrasings and four grounding phrasings from the report now refused/rejected, benign queries still route to RAG. **Residual:** regexes cannot be exhaustive. The extractive path quotes SOP text without a scope filter (unchanged). Over-refusal is possible, e.g. any question naming the FDA/EMA with submit/file/within. |
| 5 Null/non-string LLM reply | **Fixed** | `OpenRouterClient` raises `LLMError` on non-string/empty content and on `TypeError`/`AttributeError`; the temporary client is closed; `generate_answer` also guards non-httpx clients. |
| 7 `LLM_CALL` audit | **Fixed** (not in the approved list, but touched by 3) | Model name sanitised and truncated to 40 chars, chunk count kept; if the audit write fails the outbound call is blocked (fail closed) and the answer falls back to extractive. |
| 9 Hook test | **Partly fixed** | Test added for payload exclusion and registration. **Not changed:** matcher still misses NotebookEdit and Bash-driven writes; the log is a plain editable file. |
| 6 PII heuristic gaps | **Fixed (heuristic)** | `validation.py` now catches all seven reported inputs (case-insensitive name cues, `Patient Smith`, `patient: jane`, initials, 7-digit phone, `lives in` / state+ZIP, SSN/passport/MRN cues). A test confirms no shipped SOP triggers the scanner, since it also guards outbound LLM text. **Residual:** a bare name with no cue word (e.g. "Jane Doe felt dizzy") is undetectable by regex; pinned by `test_known_limit_bare_names_are_not_detected`. |
| 8 PQC drops AE fields | **Fixed** | A Product Quality Complaint with an event description or onset date is now rejected with an explicit message. The UI never sends these for PQC, so only agent/API callers see it. |
| 10 Questions change status | **Fixed** | `router.is_status_command`: only imperative messages (`move`/`close`/`update`... at the start, optional `please`) mutate status; any other message mentioning a REF is a read-only lookup. Closing by chat still only files a request. **Residual:** polite forms such as "can you move REF-... to in review?" are read-only and must be rephrased. |
| 11 Other | **Fixed, one item left** | `LOT_PATTERN` uses `[0-9]` (fullwidth digits rejected). `.gitignore` adds `data/*.db-*`. User-derived text in the Ask and Dashboard tabs goes through `ui/safe_text.escape_md`, so image/link/emoji/math markdown is inert. **Left:** `data/intake.db` still holds one `LLM_CALL` row from a manual live check; the audit log is append-only by design, the file is gitignored, and it was not deleted. Reviewer identity remains self-asserted with no requester/approver separation (see A10). |
| 1 | **n/a** | The report has no finding numbered 1; the numbering starts at 2. |
| A10 Known gaps documented | **Fixed** | Self-asserted `REV-###` identity, no requester/approver separation, forged approval by DB-file access (`DROP TRIGGER`), editable hook log and hook coverage limits are written up in `docs/defense.md`, section 6. |

Note: `tests/test_ask_ui.py::test_ask_sop_question_is_extractive_when_toggle_off` failed once on the very first run of this session and passed on every later run (cause not identified; it did not recur).
