# SOP-004 Data Privacy and Tool Scope (fictional training document)

This tool is a training prototype. Only synthetic, fictional data may be entered. Real patient names, initials, contact details, addresses, birth dates and medical history must never be entered.

The tool does not assess whether a product caused an event, does not suggest medical treatment, and does not decide whether a report must be sent to any authority. Those decisions belong to qualified staff using the enterprise pharmacovigilance system.

Free-text fields are scanned for personal data such as email addresses, phone numbers and names. A report that appears to contain personal data is rejected with an explanatory message and must be corrected before saving.

The optional answer-generation feature may send the question and a few retrieved excerpts to an external language-model service. It is switched off by default, is blocked when personal data is detected, and every outbound call is recorded in the audit trail without the text.
