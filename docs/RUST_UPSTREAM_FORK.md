# MythicSim Rust upstream fork and integration

**Owner decision (2026-11-02):** follow *all* upstream Rust changes in a public fork, keep our native world bridge and deterministic balanced RNG as actual tracked Rust commits, and consume a verified fork SHA from `forever-sim` via a Git submodule. Upstream updating does **not** remove or relax any Forever P1–P7.5 gate, source legality, P7 stochastic holdout, M1 bookkeeping or existing regression test.

- Upstream: https://github.com/sage3648/mythicsim-forever-engine
- Intended fork: https://github.com/dosibjrn/mythicsim-forever-engine
- Existing production pin: `666fe17a42682068a3c8497d88d5fa3732cbdfb9`
- Existing local patches: `integrations/mythicsim-rust/patch_world_ingress.py`, `wf652_apply_balanced.py`, `wf659_typed_rng.py`, `wf660_boolean_migration.py`, `rng_extreme_probability_fix.py`, `world_bridge.rs`.
- New workflow: `.github/workflows/rust-upstream-fork.yml`, operator script `scripts/bootstrap_mythicsim_rust_fork.sh`.

## One-time credential setup

The repository-scoped `GITHUB_TOKEN` **cannot create a fork in a user's GitHub account**. Create a short-lived classic personal access token with `public_repo`, belonging to `dosibjrn`, and save it as a GitHub Actions repository secret named **`FOREVER_RUST_FORK_TOKEN`** (never paste it into a PR or chat). Trigger **Bootstrap and sync MythicSim Rust public fork** with `workflow_dispatch` from `main`.

The bootstrap uses the token only in the trusted manual-dispatch job; PR jobs only syntax-check the script and never receive fork credentials. It verifies authenticated owner, public-fork status, correct original parent and non-force Git pushes before writing anything.

## Automated behavior and deliberate safeguards

1. Create the public fork if absent; sync its `main` by fast-forward with **all** upstream commits (no selective cherry-picks).
2. Once, check out historical upstream commit `666fe17`, run our existing bridge and balanced-RNG patcher, compile, test original quota RNG and extreme-probability regressions, run Rust library tests, and replay the frozen 10,000-iteration source reference. Commit these exact derived Rust source changes to fork branch `forever-integration`. This is a faithful conversion of build-time patching into real fork commits.
3. Merge `upstream/main` into that integration branch. If there is a conflict or any runtime/regression failure, **do not advance the integration branch**. The public fork `main` stays fully up-to-date and our previously tested integration is intact; resolve the conflict or investigate legitimate native-reference differences before retrying.
4. Only after Rust tests and historical reference regression succeed, push the integrated engine SHA to the fork. Print the SHA for the planned `forever-sim` gitlink PR.

**Not automated yet:** Adding the fork as a production submodule and migrating `.github/workflows/wf-gsim-rust-native-world.yml` plus `.github/workflows/m1-on-demand-record.yml` away from direct upstream checkout and Python patching. Those must be done in a *separate reviewed PR* with complete native↔2D integration tests. Adding a gitlink without replacing both consumers would silently leave production on `666fe17`.

Historical results may legitimately change with upstream mechanics. Do not erase the old witness or mislabel a changed score as a pass: record old/new engine SHAs, source and score; review the change, retain the historical reference, and run unchanged Forever gate predicates against a deliberately selected new pinned engine. Never automatically edit `docs/planning/M1_PASSES.tsv`.

The existing production path is unchanged until the submodule transition is fully validated and merged. The fork sync is a packaging and engine-upgrade task, not a new PROCESS gate.

## One-time Actions bootstrap dispatch (2026-11-02)

The user confirmed that `FOREVER_RUST_FORK_TOKEN` is configured. The fork bootstrap runs once from a reviewed trusted-main push with squash title `chore(rust): run fork bootstrap one-shot`, after the preflight test. No secret is passed to pull requests, no automatic production submodule promotion happens, and future pushes cannot access the token unless their *reviewed main commit message* contains the explicit one-shot title. The workflow can also be launched manually at any time; after the initial run remove the temporary push trigger and retain `workflow_dispatch`.
