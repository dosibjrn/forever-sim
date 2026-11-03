# Gate CLI: live execution is authoritative

**Owner-approved acceptance cadence (2026-11-02):** The gate CLI is an **on-demand** way to earn or revalidate a PASS, not a mandatory continuously executing test suite. An acceptance test may be a heavy direct CLI/integration run of actual production code (not necessarily a unit/pytest test). Run each active gate successfully **once** to record `PASS` and a timestamp; rerun only when relevant functional changes invalidate it. Keep fast regression checks independent from heavy formal gate acceptance. A persistent PASS timestamp needs no separate evidence JSON or committed run bundle. A stored PASS is historical acceptance, **not** authority for a new unexecuted CLI PASS.

**Active gate set (owner-approved 2026-11-03):** Only P3–P6 and P7.1–P7.5 are formal gates. P1/P2 providers and acceptance predicates are retired. The native spell/talent engine behavior remains used by the actual optimizer and relevant remaining gate paths, but no standalone P1/P2 run or evidence is required.

**P7 owner-approved stochastic acceptance (2026-11-02):** On-demand P7.1–P7.4 final comparisons use **1,000 stochastic native Rust/Go iterations** with real causal 2D coupling where required and a **0.99× saved-reference DPS floor**. P7.5 uses the same final process with a **0.93× max(saved reference, strongest accepted-compatible prior) DPS floor**. P7.2–P7.5 candidate searches instead use **deterministic low-repeat balanced RNG**, preserving their independent 300-second search budgets. Compare via the common `p7_required_dps` / `p7_final_stochastic_mean_passes` functions in `tools/wf_gate_coverage.py`. A correct numeric helper is not gate acceptance. Historical source request iteration counts remain provenance only.

The following describes the current live-provider implementation; providers must call real production code, not duplicate combat or optimization just to satisfy gate fields.

`python tools/wf_gate.py --class druid --level 60 --spec balance --gate P7.2`
calls a **Python live provider** rather than reading a prewritten PASS JSON.

- P3–P6 and P7.1–P7.5: `tools.wf_gate_<gate>_live.run_live(root, class_key, level, *, spec=...)`.
- `--gate P7` aggregates five P7 subgates; `--gate all` includes only P3–P6 and P7.1–P7.5.
- P1 and P2 are not valid CLI gate names. Requests for them are rejected by the CLI.
- Missing provider: `BLOCKED`, nonzero exit. Crashed provider: `FAIL`, nonzero exit. Generated JSON is never consulted for a pass verdict.
- A passing live report must include `runtime_proof = {executed: true, engine_revision, source_revision, run_id}`. This is **necessary but not sufficient**: provider code must genuinely execute a pinned runtime and check the formal PROCESS gate predicate; metadata alone is not a test.
- `--out` writes a fresh result, it is not an evidence source. Existing `--evidence-dir` option is retained for CLI compatibility but ignored by acceptance.
- Historical `evaluate()` JSON validators remain for diagnostic schema tests, **not** gate certification.

[GitHub Actions gate runtime authority](../../.github/workflows/gate-runtime-authority.yml) tests forged JSON rejection, code dispatch, exception handling and legacy schema rules on PRs. It is a **unit/contract CI**, not a P3–P7 gate PASS.

**Implementation direction:** retain the stable `wf_gate.py` CLI as a thin optional entry point to real production tests/searches; don't build gate-only combat engines, optimizers, synthetic scoring or redundant report plumbing. Rust/Go integration and real 2D causality requirements from [PROCESS](../../PROCESS.md) still apply where required; do not retroactively reopen owner-accepted historical P7.1 decisions without a material incompatibility.
