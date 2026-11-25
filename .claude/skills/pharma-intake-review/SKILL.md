---
name: pharma-intake-review
description: Review code in the Pharma Safety Intake & Triage Tracker against its governance checklists (data minimization, error handling, auditability, test coverage) and scope limits (no causality, treatment or reportability decisions). Use when reviewing changes, finishing a milestone, or before a demo/defense.
---

# Pharma Intake Review

Review the code (the current diff, or the whole repo if no diff is given) against four checklists. This skill reviews only; do not edit code unless the user asks.

## Procedure
1. Read `CLAUDE.md` (scope limits and architecture rules) and the files under review.
2. Work through each checklist in order. Open the checklist file, then verify every item against the actual code and tests. Do not tick an item from memory or from comments; cite `file:line` evidence.
   - `checklists/data-minimization.md`
   - `checklists/error-handling.md`
   - `checklists/auditability.md`
   - `checklists/test-coverage.md`
3. Run `python -m pytest` and record the result. Run any grep/inspection commands the checklists call for.
4. Also check the scope guardrail: nothing in code, prompts, SOPs or UI text may assess causality, recommend treatment, determine reportability, or claim to replace a pharmacovigilance system.

## Output format
For each checklist: a table of items with `PASS` / `FAIL` / `N/A`, and `file:line` evidence.
Then a findings list, most severe first, each with: severity (High/Medium/Low), location, what is wrong, a concrete failure scenario, and a suggested fix.
End with an overall verdict and any items you could not verify (say so explicitly rather than guessing).
