# Work2 — independent #2+ implementation

Read [COMMON](COMMON.md), [WORK_COMMON](WORK_COMMON.md), this file and current [WORK_PRIORITY](../WORK_PRIORITY.md). Read only the relevant OVERALL_PLAN / PROCESS / gate sections for the assigned item.

Read Work2's current issue/branch/PR from the top of WORK_PRIORITY; assignments can change and must not be hard-coded into task prompts.

## Ownership

Work2 owns the **highest independently executable #2+ item**. Continue its own assigned production path (currently determined by WORK_PRIORITY, not this file). If blocked solely by Work1's #1 dependency, take the next genuinely independent Prio item. Never take or edit Work1's branch.

For optimizer/source-related work, MythicSim Rust—not Forever Python—owns build/source-legality decisions. Do not add a new source-backed legality validator to the optimizer or recreate mechanics already owned by native Rust.

## Required cycle result

Deliver a committed/pushed, focused production delta on the assigned #2+ slice, with relevant Forever-owned regression/validation and an updated PR handoff. Do not finish with status, review or CI alone. Apply the complete start-of-cycle review, Actions inspection, PR response and no-report-only rules in WORK_COMMON.

At cycle end, consider and, when justified, launch an asynchronous paid-optimizer/100-mob regression or other relevant diagnostic on the owned code. Link its exact run/ref and hand off the next check in the existing issue/PR. Do not repeat an unchanged expensive run.
