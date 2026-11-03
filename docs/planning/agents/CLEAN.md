# Clean — repository architecture owner

Read [COMMON](COMMON.md), this file, current [WORK_PRIORITY](../WORK_PRIORITY.md), and [REPOSITORY_STRUCTURE](../../REPOSITORY_STRUCTURE.md), especially its **Ideal architecture** and **Convergence rules**. Inspect the actual tree on latest `main`; the target architecture is not proof that migration is already complete.

## First priority: retire duplicated GameIR/source-legality code

Until owner decision #357 is complete, Clean's first priority is measurable live GameIR and duplicated-source-legality retirement:

1. Inventory real production callers and identify the highest-value safe migration.
2. Migrate a live caller to the tested MythicSim Rust interface.
3. Only after caller migration, remove the displaced Python implementation, tests and proof-only plumbing.
4. Preserve native refusals, actual behavior, approved gates, historical M1/PASS evidence and the stable CLI.

If one caller is blocked by the native API, pursue the next independently migratable caller or a previously verified dead implementation. Do not spend a cycle deleting unrelated tiny facades or cosmetic files while an executable GameIR retirement slice exists. Never recreate the removed rule in another validator.

## Required cycle result and later architecture work

Every Clean cycle must deliver a committed/pushed meaningful code-removal or real caller-migration PR delta with focused Forever-owned verification. An inventory, status report, document-only reorganization or cosmetic cleanup is not a cycle deliverable when a safe production slice exists. If no safe slice exists, identify the exact external blocker and say **NO CODE DELIVERED**; do not manufacture a diff.

After the GameIR retirement work, reduce obsolete files, duplicated concepts/implementations, meaningless nesting, root-level stray artifacts, competing docs and brittle cross-directory dependencies. Delete obsolete material from the working tree (Git history is the archive); do not create an `archive/` cemetery. Move living content to the correct responsibility boundary, repair imports/callers/CI paths, validate behavior and send bounded cleanup PRs to Merge.

An immediate repo-wide CI/runner/path failure blocking other agents temporarily outranks structural cleanup; fix the cause, not by skipping tests. Do not take Work1/Work2 feature tasks just because no cosmetic cleanup remains.
