# Demo Script — Pharma Safety Intake & Triage Tracker

Target length **~14 minutes** (hard cap 15). Pairs with `docs/demo-presentation.pptx` (slide numbers below). Lines in *italics* are what to say; **bold** lines are what to do.

All data is fictional. Never type real names, dates of birth or contact details during the demo.

---

## Before you start (5 minutes, off camera)

1. Fresh throwaway database, so the REF IDs start at 0001 and the real DB stays untouched:
   ```
   cd c:\Pharma-Safety
   set PHARMA_DB_PATH=%TEMP%\demo.db        (PowerShell: $env:PHARMA_DB_PATH="$env:TEMP\demo.db")
   streamlit run app.py
   ```
2. Open http://127.0.0.1:8501. Confirm the synthetic-data banner and four tabs: Intake, Dashboard, Ask, Audit.
3. In the **Ask** tab sidebar, leave **"Allow external LLM call (OpenRouter)" OFF**. The demo then runs offline with repeatable results.
4. Keep `docs/demo-walkthrough.md` open in a second tab as the fallback. It contains real output of every step.
5. Have the slide deck open. Browser zoom 110–125% so the room can read it.

**Have these ready to copy and paste:**

| Field | Report 1 (Adverse Event) | Report 2 (Quality Complaint) |
|---|---|---|
| Report category | Suspected Adverse Event | Product Quality Complaint |
| Product name | Examplomab | Examplomab |
| Batch / lot number | LOT-88392 | LOT-12345 |
| Date received | today | today |
| Reporter type | Healthcare Professional | Consumer |
| Detailed description | Reporter described a skin reaction after a dose. | Blister packaging was torn and the label was smudged. |
| Event description | Hives and difficulty breathing | (not shown) |
| Event onset date | 2 days before today | (not shown) |

---

## 0:00 — Slide 1: Title (30 s)

*"Good [morning]. In the next thirteen minutes I'll show you a local application that captures product quality complaints and suspected adverse event reports, validates them, moves them through a lifecycle where a human has to approve closure, keeps an audit trail, and answers SOP questions with cited sources."*

*"Everything you'll see is synthetic data. And the app is deliberately limited: it never decides cause, treatment or reportability."*

## 0:30 — Slide 2: Purpose and scope (1 min)

*"The job on the left: capture, validate, track, audit, answer. On the right is the contract. The application must never assess causality, recommend treatment, determine reportability or deadlines, replace a pharmacovigilance system, or make clinical or regulatory decisions."*

*"That isn't a footnote. It's written into the project contract, enforced by a deterministic router that refuses those questions, and checked again on any generated answer. I'll show you a refusal live."*

## 1:30 — Slide 3: Architecture (1.5 min)

*"The UI is a thin Streamlit shell. Input is validated at the boundary with strict Pydantic models. Storage is plain SQLite with parameterised SQL."*

*"One design point matters: when a report is saved, the reference number, the report and the audit entry are written in one transaction. They all commit or none do."*

*"The retrieval and agent layers sit on the same database. The only thing that can leave the machine is one optional call to OpenRouter for answer generation. It's off by default, it needs a key and a toggle, it's scanned for personal data first, it sends only the question and the retrieved excerpts, and it's audited as metadata. Any failure falls back to quoting the sources."*

---

## 3:00 — Slide 4 → LIVE: Intake tab (2 min)

**Switch to the browser, Intake tab.**

1. **Select "Suspected Adverse Event".** *"The adverse-event fields appear only for this category. Switch to complaint and they disappear."* (Click Product Quality Complaint, then back.)
2. *"Notice what's not here: there are no patient identifier fields at all."*
3. **Enter only:** Product name `Examplomab`, Batch / lot `LOT-12`, Reporter type any, Description `Rash reported`. Leave event description and onset date empty. **Click Submit report.**
4. *"All the problems come back at once, each naming its field: the lot format needs LOT- and exactly five digits, and an adverse event needs an event description and onset date. It doesn't make me fix one error at a time."*
5. **Fix the form** with the Report 1 values from the table. **Submit.**
6. *"Saved. REF-2026-0001. That reference, the report and an audit row were written atomically."*
7. **Switch category to Product Quality Complaint, fill Report 2, submit.** *"And a second one, REF-2026-0002."*

*(Optional 15-second extra, if time allows:)* **Type an email address into a description and submit.** *"Free text is scanned for personal data. It's rejected."* Then remove it.

## 5:00 — Slide 5 → LIVE: Dashboard tab (2 min)

**Dashboard tab.**

1. *"Both reports, status New. I can filter by type and status."* (Use a filter once, then clear it.)
2. **Select REF-2026-0001 → click "Move to In Review".** *"New to In Review is direct."*
3. **Click "Request closure".** *"Now watch. It did not close. The report is still In Review, and the page says it's awaiting human approval. It's frozen."*
4. *"This is the human-in-the-loop gate. Closing requires a reviewer."* **In the approval form enter:** Reviewer ID `REV-001`, role `QA Lead`, rationale `Documentation complete; closure approved.` **Click "Approve closure".**
5. *"Only now is it Closed. The reviewer ID is pseudonymous, never a name, and the rationale is stored with the approval, not in the audit log."*
6. **Select REF-2026-0002 and try "Request closure" while it's New.** *"And a New report can't skip to Closed. The allowed order is New, In Review, Closed."*
7. *"The same rule is enforced a second time by database triggers, so ordinary SQL can't forge an approval either. I'll be upfront about the limit of that later."*

## 7:00 — Slide 6 → LIVE: Audit tab (1 min)

**Audit tab.**

*"Everything we just did is here: report created, status changed, closure requested, closure approved by REV-001. Each row has a UTC timestamp, an action from a fixed vocabulary, the REF, a short controlled detail and the actor."*

*"What's not here is any free text. Descriptions and rationale never go in the audit log, and database triggers block updating or deleting rows. The viewer is read-only."*

---

## 8:00 — Slide 7: Hybrid RAG (1.5 min)

*"For questions, retrieval runs in four stages over the SOPs and the saved reports. BM25 is exact-token matching, so an identifier like LOT-88392 stays one token. A dense encoder handles meaning, so 'difficulty breathing' matches 'dyspnea'. Reciprocal rank fusion merges the two ranked lists. A reranker then scores each question and excerpt pair from zero to one, and anything under 0.40 is dropped, with at most five kept."*

*"Then the guardrails: if nothing is relevant enough, the language model isn't called at all. If it is called, every sentence must carry a valid source citation and none may contain causality, treatment or reportability wording. Anything that fails falls back to quoting the sources."*

## 9:30 — Slide 8 → LIVE: Ask tab (2.5 min)

**Ask tab. Confirm the toggle is OFF.** For each query type it in the box and click **Send**.

1. `LOT-88392 hives` — *"Exact lot match: it finds our saved report and an SOP terminology note, with source labels."* **Open the "Retrieval trace" expander.** *"Here's BM25 candidates, dense candidates, the fused pool and the reranker scores."*
2. `difficulty breathing` — *"Different words, same concept. It finds the dyspnea terminology note through the synonym lexicon."*
3. `xqzvv plorb wibble` — *"Gibberish. 'No sufficiently relevant source found.' It doesn't invent an answer."*
4. `Did Examplomab cause the reaction?` — *"A causality question. Fixed refusal. This is the scope boundary working. We deliberately didn't make this 'helpful'."*
5. *(Optional, 20 s)* `move REF-2026-0002 to in review`, then `close REF-2026-0002` — *"Chat can move a report to In Review. Asking it to close only files a request and says PENDING_APPROVAL. No agent tool can approve a closure."*

**If asked about the AI model:** *"The toggle in the sidebar enables one external call. I've kept it off so this demo is offline and repeatable. With it on, the answer must pass the citation and scope checks or it falls back to extractive quoting."* Don't promise a specific live LLM answer; if you try one, use `Who approves a closure?` and be ready for a fallback.

## 12:00 — Slide 9: Control plane (1.5 min)

*"The Ask tab sits on a control plane. A pure rule-based router runs first: refuse beats greeting beats status beats intake beats retrieval. Tool calls are auto-repaired for typos and aliases, then validated against strict schemas, then checked against the domain rules."*

*"There's also a circuit breaker. If the same tool call fails validation three times in a row, execution halts, the trip is audited, and all tools stay stopped until reset. On the slide you can see calls one and two fail, the third opens the circuit. Ordinary business rejections, like an illegal transition, don't count toward it."*

*(The breaker can't be triggered from chat, so show it from the slide's real output.)*

## 13:30 — Slides 10–11: Governance and limits (1.5 min)

*"How this was built matters in a regulated setting. A project contract is loaded every session. A hook, run by the tooling and not by the model, logs only timestamp, tool and path for every file edit, never content. An independent review against four checklists found ten issues; all are fixed with regression tests. There are 239 automated tests, none touching the network."*

*"And honest limits. Reviewer identity is self-asserted and there's no separation between requester and approver. Anyone with write access to the database file could drop the triggers, so the file is trusted and the app is bound to localhost. The scope and PII checks are pattern-based, so they can miss or over-refuse. Production would need authentication and roles, an encrypted database, a tamper-evident audit, 21 CFR Part 11 validation, integration with a real pharmacovigilance system and a review of the LLM vendor."*

## 14:30 — Slide 12: Takeaways (30 s)

*"Three takeaways. Scope is enforced, not just promised. The human stays in the loop by construction. And the claims are backed by tests and an audit trail. Happy to take questions."*

---

## If something goes wrong

| Problem | Say / do |
|---|---|
| Streamlit page won't load | *"Let me show you the recorded output of the same run."* Open `docs/demo-walkthrough.md`. Regenerate it any time with `python scripts/demo.py`. |
| Ask tab is slow on the first query | It builds the search index on first use. *"It's indexing the SOPs and reports on first use."* Wait a few seconds. |
| A form rejects your input | Use it as the demo: read the error aloud, fix it. |
| You run over time | Skip the optional steps, and compress slides 9–11 into two sentences each. |
| Asked "does it work with real data?" | *"No. It's a synthetic-data training prototype and says so on every screen."* |
| Asked "can it say if this is reportable / caused by the drug?" | *"No, by design. That belongs to qualified staff in the enterprise system."* |
| Asked "can I use the LLM?" | Only if a key is configured. Off by default; opt-in, scanned, audited; falls back to quoting sources. |

## Likely questions

- **Why not let the agent approve closures?** Closure is a regulated decision; the design makes a human record it, and the database rejects anything else.
- **How do you know the guardrails work?** 239 tests, including adversarial phrasings, plus an independent review whose findings were fixed. The checks are heuristics, so I've listed their limits.
- **Is the audit log tamper-proof?** Not against someone with file access. Production needs a hash chain or write-once storage.
- **What leaves the machine?** Nothing, unless the OpenRouter toggle is on; then only the question and the retrieved excerpts, after a PII scan.
