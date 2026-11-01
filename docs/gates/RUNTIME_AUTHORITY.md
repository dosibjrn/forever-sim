# Gate CLI: live execution is authoritative

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

**Next small worker item:** implement one genuinely executed provider, starting with P3 for one checkpoint. No provider is installed for the remaining gates in this change: they remain blocked. Rust/Go integration and genuine 2D causality requirements from [PROCESS](../../PROCESS.md) still apply where required; never retroactively reopen an owner-accepted historical P7.1 decision.
