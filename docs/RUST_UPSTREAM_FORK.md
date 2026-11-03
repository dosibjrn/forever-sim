# Canonical MythicSim Rust fork and exact source integration

## Owner instruction (2026-11-03)

**Ship the latest patched Rust source into `forever-sim` and move on to the NEXT gates. Do not revalidate MythicSim itself.** Forever's mechanics legitimately change with upstream patches, so historical numeric DPS references are NOT required to stay identical. Every previously accepted P1–P7.5 gate PASS remains accepted; **never erase, retimestamp, downgrade or rerun a historical PASS merely because the Rust source changed.** M1 acceptance/ledger and source packaging are separate workflows.

- Original upstream: https://github.com/sage3648/mythicsim-forever-engine
- Owned public fork: https://github.com/dosibjrn/mythicsim-forever-engine
- `fork/main` fast-forwards and preserves **all** upstream commits.
- `fork/forever-integration` merges upstream history with our real Rust-source native 2D world bridge, typed Balanced RNG, extreme probability handling, and new upstream Paladin RNG callsites. Preserve these patches as tracked Rust commits, never duplicate combat effects in Python.
- `forever-sim` consumes **one exact fork integration commit** as a native Git submodule, `integrations/mythicsim-rust/engine`. The gitlink is the source identity for both live native-world CI and Merge's P7 on-demand gate worker, never a floating branch.
- **Current transition vs approved target (#357/#359):** pinned Rust already owns its implemented combat spells, talents, procs and effects, while existing Forever code still performs SQLite-backed source/level selection, GameIR/gsim execution and 2D world/controller work. These are **live transitional dependencies, not permanent client responsibilities**. The target moves *all* game facts, eligibility/legality and game-world/2D/chainpull execution behind the tested MythicSim Rust interface. Forever retains scenario definitions, candidate search, scoring, process validation and engine/evidence provenance only. Move callers and prove native positive/negative behavior before deleting legacy paths; do not duplicate mechanics or waive a gate.
- Existing gsim/GameIR code and passing tests are preserved until replacement is actually working. That migration does not open previously accepted gates.

## Packaging operation

`scripts/bootstrap_mythicsim_rust_fork.sh` and `.github/workflows/rust-upstream-fork.yml` require the already-configured `FOREVER_RUST_FORK_TOKEN`. They fetch/merge **all** upstream code, apply tracked Rust changes, use fail-closed source-patch anchors, and run only `cargo check --locked` to confirm the source can be compiled. **No old DPS parity check, revalidation of msim, P1–P7.5 acceptance, or M1 ledger editing is performed.** A compile failure is a package/build defect and must be fixed in Rust, not a reason to revisit historical gate evidence.

Next: push the exact integration SHA to the fork, record it in the parent repository gitlink, move both existing engine users to the gitlink, then continue the highest-priority unfinished gates. The temporary trusted-main push kickoff is removed once the source-sync Actions run is started; manual `workflow_dispatch` remains.

For old bootstrap attempts and decisions, use Git history and the existing issues. Historical saved DPS fixtures and recorded PASS receipts remain unchanged.
