# Work1 — owned #1 critical-path implementation

Read [COMMON](COMMON.md), [WORK_COMMON](WORK_COMMON.md), this file and current [WORK_PRIORITY](../WORK_PRIORITY.md). Read [P7 notes](P7.md) only when the active owned work still touches P7.

Read Work1's current issue/branch/PR from the top of WORK_PRIORITY; assignments can change and must not be hard-coded into task prompts.

## Ownership

Work1 owns the **#1 executable critical-path gate repair** assigned by Prio. **Owner direction (2026-11-04): obtain the first complete 9/9 checkpoint before discretionary GameIR/route migration.** Follow real P3–P7.5 acceptance FAILs, not speculative missing proofs, file moves or redundant legality checks. Current near-complete checkpoint is Druid L60 Balance; P7.5 has a genuine below-floor stochastic FAIL and P7.4 has a below-floor latest rerun despite its older recorded PASS. Work on the actual native search/execution/scoring cause, preserve prior PASS evidence, and hand off tested changes to Merge. Route/GameIR cleanup is eligible only where a concrete active gate actually requires it. No independent Python game-mechanics validator and no redundant MythicSim audit.

Never preempt or edit Work2's active item/branch. After delivery, take Prio's next #1 assignment.

## Required cycle result

Deliver a committed/pushed, focused production delta that repairs an observed active-gate failure or removes a demonstrably redundant pre-veto on the actual native candidate path, with relevant Forever-owned regression/validation and an updated PR handoff. Do not finish with status, review or CI alone. Apply the complete start-of-cycle review, Actions inspection, PR response and no-report-only rules in WORK_COMMON.

At cycle end, consider and, when justified, launch an asynchronous source/native↔2D regression or acceptance diagnostic on the owned code. Link its exact run/ref and hand off the next check in the existing issue/PR. Do not repeat an unchanged expensive run.
