# Work1 — owned #1 critical-path implementation

Read [COMMON](COMMON.md), [WORK_COMMON](WORK_COMMON.md), this file and current [WORK_PRIORITY](../WORK_PRIORITY.md). Read [P7 notes](P7.md) only when the active owned work still touches P7.

Read Work1's current issue/branch/PR from the top of WORK_PRIORITY; assignments can change and must not be hard-coded into task prompts.

## Ownership

Work1 owns the highest-impact **real active-gate production repair** delegated by Prio. The owner clarification on 2026-11-04 is that **P1, P2 and GameIR are to be deleted**, not preserved by creating new native-route adapters. Clean owns dead-code retirement; Work1 must not create or extend an adapter solely to migrate retired P1/P2 checks, historical GameIR demos, bounded route evidence or diagnostic-only 100-target routes.

Owner priority is the first complete 9/9 checkpoint before discretionary GameIR/route cleanup. The latest production rechecks measured P7.4 **692.819689 < 720.9117** and P7.5 **616.177645 < 677.220060**; these are real FAILs despite older accepted receipts. Current Work1 lane: finish and hand off the existing Druid L60 Balance P7.5 production candidate-reachability repair (#718), then identify and fix the measured DPS shortfall on the actual P7.5 executor. Hold standalone no-gate route-candidate PRs #715/#716 unless an active P3–P7.5 gate or real optimizer caller demonstrably requires their code. If such a need is proven, reuse the smallest existing selected-MythicSim boundary and delete the displaced GameIR caller rather than adding wrappers, redundant checks or a new diagnostic suite.

Do not edit Work2's active item/branch. Preserve existing accepted M1 evidence.

## Required cycle result

Deliver a committed/pushed, focused production delta on the assigned live gate/optimizer repair or another executable #1 slice, with relevant Forever-owned regression/validation and an updated PR handoff. Do not finish with status, review or CI alone. Apply the complete start-of-cycle review, Actions inspection, PR response and no-report-only rules in WORK_COMMON.

At cycle end, consider and, when justified, launch an asynchronous source/native↔2D regression or acceptance diagnostic on the owned code. Link its exact run/ref and hand off the next check in the existing issue/PR. Do not repeat an unchanged expensive run.
