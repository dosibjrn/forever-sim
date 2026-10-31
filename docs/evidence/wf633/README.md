# WF633 — pinned Rust Balance reference replay

**Diagnostic evidence PASS**, additionally accepted by the owner specifically as **Balance L60 P7.1** via Rust engine. This does not establish a native Go or live 2D run.

- [Reconstructed frozen RaidSimRequest](rust_request_reconstructed.json) (gear IDs, enchants, talents, rotation/APL, consumes, buffs, debuffs, encounter, iterations and RNG seed)
- [Full Rust result](rust_result.json) including DPS distribution and combat events
- [Validator](WF633_VALIDATION.json): request hash, engine revision, DPS difference
- [Small reproducible runner](../../../integrations/mythicsim-rust/verify_reference.py)
- [Original build and scenario summary](../rust-reference-replay.md)
- [User acceptance record](../druid-p7/README.md)

Upstream source: [MythicSim Rust commit `666fe17a4`](https://github.com/sage3648/mythicsim-forever-engine/tree/666fe17a42682068a3c8497d88d5fa3732cbdfb9), built via [GitHub Actions WF632](https://github.com/dosibjrn/dite/actions/runs/40879414059), artifact `wf632-forever-engine-linux-x64`. The repository's [pinned engines CI](../../../.github/workflows/build-pinned-engines.yml) can build a compatible Rust executable.

Reproduction: `python integrations/mythicsim-rust/verify_reference.py --engine /path/to/forever-engine` (from repository root). This invokes the *real Rust binary*, validates source/config hash, runs the full request and checks the recorded stochastic result.

Measured: `728.1936126415858 DPS` (10,000 fights, seed `1179706472`, duration 120 ± 15 s; stdev `43.420319553486735`). Reference `728.1936126415858`. Delta zero. Input SHA256 `d4f659e066a9aaf7ba9f389391e2490415308b65a9e074fa696b18e97ec83226`. Exact original *raw* report JSON bytes were not available; the reconstructed input reproduced the result.

The genuine Go and interactive gsim-2D runtime acceptance semantics in approved PROCESS are a separate unproven implementation path; do not infer them from Rust alone. The documented owner exception does not automatically change P7.2–P7.5 runtime criteria.
