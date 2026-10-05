---
description: Updates docs/progress.md at the end of a work session: checklist, requirements status, session log, deviations, known issues and next task, using real test results.
---

# Update progress

Follow these steps in order.

1. Read docs/progress.md and docs/architecture.md.
2. Review what was changed in this conversation (files created or edited, features added).
3. Run the project's test suite. Record the real results (passed, failed, skipped). If tests cannot run, say so and explain why. Never invent results.
4. Update docs/progress.md:
   - Tick completed items in the phase checklist, but only if their acceptance tests ran and passed.
   - Update the requirements status (C1-C3, G1-G7, S1-S3) the same way.
   - Add a new entry at the top of the session log: date, phase, what was done, tests run and results, files changed, what is unfinished.
   - Record any deviation from docs/architecture.md under "Decisions and deviations", with the reason.
   - Update "Known issues / TODO".
   - Set "Current phase", "Last completed task" and "Next task".
5. If docs/progress.md and the actual code disagree, report the mismatch to me instead of guessing.
6. Show me a summary of what changed in docs/progress.md. Do not change any other files.