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
3. Merge `upstream/main` into that integration branch. If there is a conflict or any runtime/regression failure, **do not advance the integration branch**. The public fork `main` stays fully up-to-date and our previously tested integration is intact; resolve the conflict or investigate legitimate native-reference differences before retrying. The original saved baseline MUST replay exactly on its original pinned Rust source before this merge; an upgraded engine can give a different DPS. Its new DPS is recorded alongside unchanged old source/SHA and verified through live native↔2D, without rewriting the old immutable witness.
4. Only after native Rust and deterministic balanced RNG tests, the old baseline historical replay, new upstream source identity and real native↔gsim world comparison succeed, push integrated engine SHA to fork. The new candidate's changed 1,000-stochastic mean and delta are preserved as a diagnostic comparison, **not** a certified P7 PASS. Print the SHA for the planned `forever-sim` gitlink PR.

**Not automated yet:** Adding the fork as a production submodule and migrating `.github/workflows/wf-gsim-rust-native-world.yml` plus `.github/workflows/m1-on-demand-record.yml` away from direct upstream checkout and Python patching. Those must be done in a *separate reviewed PR* with complete native↔2D integration tests. Adding a gitlink without replacing both consumers would silently leave production on `666fe17`.

Historical results may legitimately change with upstream mechanics. Do not erase the old witness or mislabel a changed score as a pass: record old/new engine SHAs, source and score; review the change, retain the historical reference, and run unchanged Forever gate predicates against a deliberately selected new pinned engine. Never automatically edit `docs/planning/M1_PASSES.tsv`.

The existing production path is unchanged until the submodule transition is fully validated and merged. The fork sync is a packaging and engine-upgrade task, not a new PROCESS gate.

## One-time Actions bootstrap dispatch (2026-11-02)

The user confirmed that `FOREVER_RUST_FORK_TOKEN` is configured. We launched the initial bootstrap using a one-time reviewed trusted-main push at commit `acd7c2bf6eeca5eb945fcd3db04a1aa3e5451276` (Actions run `41518082153`). The public fork was created. **The temporary push trigger is removed:** future syncs require manual `workflow_dispatch` or a separately reviewed scheduled mechanism. No secret is passed to PR runs. No production submodule or P1–P7.5 gate was automatically promoted.

## Recorded observed upstream reference change (first run)

[Initial bootstrap](https://github.com/dosibjrn/forever-sim/actions/runs/41518082153) succeeded on 352/352 updated Rust library tests and compiled the integration branch. **The original patched `666fe17` source exactly replayed 728.1936126415858 DPS (PASS)** before merge. Full upstream merge produced candidate Rust commit `0cc8d7942822f1bc8e181c3ed4a17f30886586d8` and source replay 760.1228838919874 DPS, so the exact-baseline check correctly failed. Those are separate engine semantics, not evidence to reset the historical 728 result. New `verify_upstream_candidate.py` records changed-native DPS and requires selected actual native↔real-2D causal parity in stochastic and balanced modes, including Mage and Hunter pet/prepull sources. This diagnostics-only workflow is not a new PROCESS gate; formal P7 keeps its own approved 1,000-stochastic, 1% reference-floor and real-2D requirements. A one-shot retry is reviewed separately and the temporary push trigger will be removed again after run.
