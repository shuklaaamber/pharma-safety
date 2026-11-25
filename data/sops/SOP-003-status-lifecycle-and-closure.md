# SOP-003 Status Lifecycle and Closure Approval (fictional training document)

Every report moves through three statuses in order: New, then In Review, then Closed. A status cannot be skipped and a Closed report cannot be reopened in this tool.

Moving a report from New to In Review is done by the intake operator and is recorded in the audit trail.

Closing a report requires human compliance approval. The operator submits a closure request; the report stays In Review and is frozen until a reviewer records a decision. The reviewer enters a pseudonymous reviewer ID in the form REV-123, selects a role (Compliance Reviewer or QA Lead) and writes a short rationale of at most 200 characters. If the closure is rejected, the report stays In Review and a new closure request may be made later.

All status changes, closure requests and reviewer decisions are written to the append-only audit trail. The audit trail records the action, time and reference only, never the report description.
