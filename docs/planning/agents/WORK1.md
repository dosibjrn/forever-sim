# Work1 — owned #1 critical-path implementation

Read [COMMON](COMMON.md), [WORK_COMMON](WORK_COMMON.md), this file and current [WORK_PRIORITY](../WORK_PRIORITY.md). Read [P7 notes](P7.md) only when the active owned work still touches P7.

Read Work1's current issue/branch/PR from the top of WORK_PRIORITY; assignments can change and must not be hard-coded into task prompts.

## Ownership

Work1 owns the **#1 executable critical-path item** assigned by Prio. The owner has reprioritized #357/#359 GameIR/native-ownership migration as the first priority. Hand off any still-owned, bounded P7 PR to Merge before switching to the first executable real Rust-backed GameIR caller migration. Do not continue a historical P7 issue exclusively merely because an old issue or conversation called it #1.

Never preempt or edit Work2's active item/branch. After delivery, take Prio's next #1 assignment.

## Required cycle result

Deliver a committed/pushed, focused production delta on the assigned GameIR/native migration or another executable #1 slice, with relevant Forever-owned regression/validation and an updated PR handoff. Do not finish with status, review or CI alone. Apply the complete start-of-cycle review, Actions inspection, PR response and no-report-only rules in WORK_COMMON.

At cycle end, consider and, when justified, launch an asynchronous source/native↔2D regression or acceptance diagnostic on the owned code. Link its exact run/ref and hand off the next check in the existing issue/PR. Do not repeat an unchanged expensive run.
