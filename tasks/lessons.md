# Lessons Learned

- [2026-02-23] [wrong-approach] LLM failed Aetna EOB extraction 3 times (wrong amounts, wrong patients, $0.00) — should have stopped after attempt 2 and proposed deterministic parsing immediately instead of more prompt engineering
- [2026-02-23] [scope-creep] Built Aetna parser iteratively without a plan — touched 3+ files, should have written numbered checklist per Rule 3 and waited for approval
- [2026-02-23] [error-handling] Didn't dry-run parser before real run — service_type field had raw payment summary text with dollar amounts. Always verify output with --dry-run before writing to production sheet
- [2026-02-23] [wrong-approach] Didn't verify sheet contents after writing — missed that service_type was polluted, Amount column appeared empty in formatted view. Always read back what was written
- [2026-02-23] [process] Didn't run code simplifier, create PR, or do code review before declaring done — follow full workflow: fix → simplify → commit → PR → review
