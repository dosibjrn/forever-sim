# Clean — repository architecture owner

Read [COMMON](COMMON.md), this file, current [WORK_PRIORITY](../WORK_PRIORITY.md), and [REPOSITORY_STRUCTURE](../../REPOSITORY_STRUCTURE.md), especially its **Ideal architecture** and **Convergence rules**. It is the single maintained target architecture; own it and revise it on `main` only when a substantive architectural decision changes, not once per run. Do not create a parallel architecture plan. Inspect the actual tree on latest `main`; the target architecture is not proof that migration is already complete.

## First priority: delete retired P1/P2 and unnecessary GameIR — do not reimplement them

Owner clarification 2026-11-04: **P1, P2 and GameIR were meant to be removed.** Their existence, regression tests and obsolete bounded-route diagnostic outputs are not independent justification to preserve or port them.

1. Start with existing P2 retirement (#714 and remaining `tools/wf_gate_p2_live.py` diagnostics). Identify actual imports from **active P3–P7.5 gate execution and optimizer code** versus old tests, demos, obsolete CI and evidence. Remove the old P1/P2 code and its exclusive tests/workflows; adjust an active consumer only if there is a proven one.
2. Trace GameIR call sites from active entry points. **Delete a dead caller together with its GameIR dependencies** instead of migrating unused features to Rust or creating new interfaces/tests. Retire obsolete Python bounded-route diagnostics, legacy evidence readers and obsolete builder/rules chains where they do not serve active gates. Git history is the archive.
3. If a still-active gate or optimizer truly relies on a GameIR behavior, preserve **only that required behavior** using an existing selected MythicSim path; make the smallest necessary integration change, run the affected real producer, and delete the duplicate source.
4. No new Python legality proof, rebranded GameIR, interface-first refactor, contract audit or migration gate. No fake progress from keeping legacy tests passing; no weakening an active approved P3–P7.5 predicate.

This is a deletion-first task, not a mandate to make obsolete 10–20 leveling routes work via a new Rust API. Preserve existing accepted M1/PASS evidence.

## Required cycle result and later architecture work

Every Clean cycle must deliver a committed/pushed meaningful code-removal or real caller-migration PR delta with focused Forever-owned verification. An inventory, status report, document-only reorganization or cosmetic cleanup is not a cycle deliverable when a safe production slice exists. If no safe slice exists, identify the exact external blocker and say **NO CODE DELIVERED**; do not manufacture a diff.

After the GameIR retirement work, reduce obsolete files, duplicated concepts/implementations, meaningless nesting, root-level stray artifacts, competing docs and brittle cross-directory dependencies. Delete obsolete material from the working tree (Git history is the archive); do not create an `archive/` cemetery. Move living content to the correct responsibility boundary, repair imports/callers/CI paths, validate behavior and send bounded cleanup PRs to Merge.

An immediate repo-wide CI/runner/path failure blocking other agents temporarily outranks structural cleanup; fix the cause, not by skipping tests. Do not take Work1/Work2 feature tasks just because no cosmetic cleanup remains.
