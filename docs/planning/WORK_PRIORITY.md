# FOREVER SIM — active work priority

**Purpose:** the smallest current execution queue toward **148/148 genuinely certified checkpoints** in minimum total time. Prio owns this queue. **Work1 keeps #1; Work2 takes the highest independent #2+.** Reassign only for a real dependency/priority change, preserving in-flight work.

This file is **not a changelog, PR queue, evidence register or second process**:
- **History and completed decisions:** `git log --follow -p -- docs/planning/WORK_PRIORITY.md`, [Git history](https://github.com/dosibjrn/forever-sim/commits/main/docs/planning/WORK_PRIORITY.md) and linked issues/PRs. Do not paste history back here or create an archive file.
- **Actual live M1 status:** [M1_PASSES.tsv](M1_PASSES.tsv), computed by `python tools/m1_progress.py`; never hardcode old PASS/PARTIAL numbers here.
- **Agent roles/merge rules:** [AUTONOMOUS_AGENTS.md](AUTONOMOUS_AGENTS.md). **What/how/acceptance:** [OVERALL_PLAN](../../OVERALL_PLAN.md), [PROCESS](../../PROCESS.md) and [P1–P7.5](../gates/README.md). **Architecture:** [REPOSITORY_STRUCTURE](../REPOSITORY_STRUCTURE.md). Detailed tasks and evidence belong in the issues and implementation PRs.

## Active queue

| Order / owner | Current issue | Next verifiable production result |
| --- | --- | --- |
| **#1 — Work1** | [#7: native Rust ↔ real gsim 2D P7](https://github.com/dosibjrn/forever-sim/issues/7) | Resolve actual saved reference/UI and legal gear/enchant/talent/APL coverage, source/engine/scenario compatibility and strongest accepted-compatible P7.5 prior. Reuse the existing P7.2–P7.5 cold-search/holdout execution paths; fix the first real RED, then run justified full independent 300 s + frozen 1,000-stochastic acceptance (not hourly). No second engine or invented reference. |
| **#2 — Work2 (independent)** | [#19: paid persistent 100-mob evaluator](https://github.com/dosibjrn/forever-sim/issues/19), [#15: joint legal optimizer](https://github.com/dosibjrn/forever-sim/issues/15) | Close actual candidate-space/source legality and selected native↔2D backend gaps in the existing P4/P5 30/300 s paths. Prove paid, source-matched 100 consecutive mobs with retained actor state/recovery, independent cold winners and P6 replay; no gsim-only hybrid PASS. |
| **Prio — parallel source/gate work** | [#131](https://github.com/dosibjrn/forever-sim/issues/131), [#11: P1](https://github.com/dosibjrn/forever-sim/issues/11), [#12: P2](https://github.com/dosibjrn/forever-sim/issues/12) | Fix the next real P2 talent-effect RED on the selected source-backed executor: restore missing rank effect families through the existing generic source→runtime compiler, then verify actual behavior and optimizer reachability in the production P2 gate. Nature's Reach still needs its sourced world/range effect; coordinate that seam with Work1 rather than duplicating its engine. Independently resolve P1 learned-rank source evidence and applicable selected-engine effect probes. Merge alone records the already-integrated P3 repair. |
| **Merge — ongoing** | [Current PRs](https://github.com/dosibjrn/forever-sim/pulls) | Review and merge safe tested increments; collect `M1 affected gates:` from each merged PR; launch the existing targeted live recorder. **Only Merge/its trusted Action writes M1.** A mergeable increment need not already be a full gate PASS. |
| **Clean — ongoing** | [Repository structure](../REPOSITORY_STRUCTURE.md) | Continue the highest-impact safe structural convergence, including removing obsolete duplication. Do not create parallel architectures, history archives, feature engines or reporting systems. |

## Next-decision rule

At each Prio cycle, check **latest `main` + active issues/PRs + actual gate evidence**, then change **only a row whose next executable action or ownership really changed**. Work1/Work2 continue unfinished owner issues/branches rather than starting new work from an old PR number. Keep independent lanes moving toward the first compatible **11/11 checkpoint**, then reuse the same production path for the other 147.

**Priority-document hygiene:** replace superseded instructions in place; do **not append** dated status paragraphs, merged-PR lists, historical CI failures, old HEADs, past M1 snapshots, run-by-run summaries or retrospective timelines. They remain discoverable through Git, PRs and Actions. Keep this page short enough to read at the start of every agent cycle. Tests, blockers and handoff receipts go to the relevant issue/PR. Do not loosen PROCESS gates or manufacture PASSes.
