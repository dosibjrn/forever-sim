# Gate CLI: live execution is authoritative

**Owner-approved acceptance cadence (2026-11-02):** The gate CLI is an **on-demand** way to earn or revalidate a PASS, not a mandatory continuously executing test suite. An acceptance test may be a heavy direct CLI/integration run of actual production code (not necessarily a unit/pytest test). Run each gate successfully **once** to record `PASS` and a timestamp; rerun only when relevant functional changes invalidate it. Keep fast regression checks independent from heavy formal gate acceptance. A persistent PASS timestamp needs no separate evidence JSON or committed run bundle. A stored PASS is historical acceptance, **not** authority for a new unexecuted CLI PASS.

The following describes the current live-provider implementation; providers must call real production code, not duplicate combat or optimization just to satisfy gate fields.

`python tools/wf_gate.py --class druid --level 60 --spec balance --gate P7.2`
now calls a **Python live provider** rather than reading a prewritten PASS JSON.

- P1: `tools.wf_gate_p1_live.run_live(...)` (existing).
- P2: `tools.wf_gate_p2_live.run_live(...)` (existing).
- P3–P6 and P7.1–P7.5: `tools.wf_gate_<gate>_live.run_live(root, class_key, level, *, spec=...)`.
- `--gate P7` aggregates five P7 subgates; `--gate all` includes P1–P6 and P7.1–P7.5.
- Missing provider: `BLOCKED`, nonzero exit. Crashed provider: `FAIL`, nonzero exit. Generated JSON is never consulted for a pass verdict.
- A passing P3+ live report must include `runtime_proof = {executed: true, engine_revision, source_revision, run_id}`. This is **necessary but not sufficient**: provider code must genuinely execute a pinned runtime and check the formal PROCESS gate predicate; metadata alone is not a test.
- `--out` writes a fresh result, it is not an evidence source. Existing `--evidence-dir` option is retained for CLI compatibility but ignored by acceptance.
- Historical `evaluate()` JSON validators remain for diagnostic schema tests, **not** gate certification.
- Existing standalone P1/P2 live probes still execute directly. Their independently produced detailed outputs can be recorded for audit.

[GitHub Actions gate runtime authority](../../.github/workflows/gate-runtime-authority.yml) tests forged JSON rejection, code dispatch, exception handling and legacy schema rules on PRs. It is a **unit/contract CI**, not a P3–P7 gate PASS.

**Implementation direction:** retain the stable `wf_gate.py` CLI as a thin optional entry point to real production tests/searches; don't build gate-only combat engines, optimizers, synthetic scoring or redundant report plumbing. For still-unimplemented gates, make the **first real executed acceptance test** work through the selected production path (P3 gear smoke is a possible small starting slice). Missing providers still report BLOCKED when invoked; do not turn a schema/CI check into acceptance. Rust/Go integration and real 2D causality requirements from [PROCESS](../../PROCESS.md) still apply where required; do not retroactively reopen owner-accepted historical P7.1 decisions without a material incompatibility.
