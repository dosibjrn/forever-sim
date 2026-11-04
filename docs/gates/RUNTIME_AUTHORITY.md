# Gate CLI: live execution is authoritative

**Owner-approved v2.20 (2026-11-03):** P1 abilities and P2 talents are retired from formal acceptance. The active CLI and M1 recorder expose only P3–P6 and P7.1–P7.5 (nine gates per checkpoint). P1/P2 providers, validators, probes, evidence readers and dedicated test routes are retired; historical ledger rows remain preserved but cannot be invoked by this CLI or recorded as new M1 PASS.

**Owner-approved acceptance cadence (2026-11-02):** The gate CLI is an **on-demand** way to earn or revalidate a PASS, not a mandatory continuously executing test suite. An acceptance test may be a heavy direct CLI/integration run of actual production code (not necessarily a unit/pytest test). Run each gate successfully **once** to record `PASS` and a timestamp; rerun only when relevant functional changes invalidate it. Keep fast regression checks independent from heavy formal gate acceptance. A persistent PASS timestamp needs no separate evidence JSON or committed run bundle. A stored PASS is historical acceptance, **not** authority for a new unexecuted CLI PASS.

**Current P7 authority (PROCESS v2.22):** P7.1 and P7.5 alone require 1,000 genuine native stochastic fights (99% frozen reference and 93% comparator respectively). P7.2–P7.4 require a genuinely paid distinct legal single-axis candidate, not independent 300s searches/holdouts or live 2D. See [P7](P7.md); runtime helpers must follow that contract rather than resurrect old 0.99× axis checks.

The following describes the current live-provider implementation; providers must call real production code, not duplicate combat or optimization just to satisfy gate fields.

`python tools/wf_gate.py --class druid --level 60 --spec balance --gate P7.2`
now calls a **Python live provider** rather than reading a prewritten PASS JSON.

- P1/P2: retired; historical providers are not part of active acceptance.
- P3–P6 and P7.1–P7.5: `tools.wf_gate_<gate>_live.run_live(root, class_key, level, *, spec=...)`.
- `--gate P7` aggregates five P7 subgates; `--gate all` includes P3–P6 and P7.1–P7.5.
- Missing provider: `BLOCKED`, nonzero exit. Crashed provider: `FAIL`, nonzero exit. Generated JSON is never consulted for a pass verdict.
- A passing active live report must include `runtime_proof = {executed: true, engine_revision, source_revision, run_id}`. This is **necessary but not sufficient**: provider code must genuinely execute a pinned runtime and check the formal PROCESS gate predicate; metadata alone is not a test.
- `--out` writes a fresh result only. The CLI has no saved-evidence input; historical JSON never participates in acceptance.
- No P1/P2 diagnostic or manual test suite remains in the active CLI/workflows.

Focused CLI regressions live in `tests/gates/test_wf_gate_class_cli.py` and `tests/gates/test_wf_gate_runtime_authority.py`. They verify active dispatch and response handling; they are **not** P3–P7 gate PASS evidence.

**Implementation direction:** retain the stable `wf_gate.py` CLI as a thin optional entry point to real production tests/searches; don't build gate-only combat engines, optimizers, synthetic scoring or redundant report plumbing. For still-unimplemented gates, make the **first real executed acceptance test** work through the selected production path (P3 gear smoke is a possible small starting slice). Missing providers still report BLOCKED when invoked; do not turn a schema/CI check into acceptance. Rust/Go execution and P4–P6 spatial 2D causality requirements from [PROCESS](../../PROCESS.md) still apply where required; do not retroactively reopen owner-accepted historical P7.1 decisions without a material incompatibility.
