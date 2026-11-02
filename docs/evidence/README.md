# Evidence index

This directory indexes **optional historical and reproducibility evidence**, not a mandatory per-gate certification bundle. The canonical accepted PASS/PARTIAL register is [`M1_PASSES.tsv`](../planning/M1_PASSES.tsv), updated by the Merge-owned on-demand runner; see [PROCESS](../../PROCESS.md) and the [gate contracts](../gates/README.md). A real accepted gate needs an executed production predicate and may retain only PASS plus timestamp. Do not create a directory or a duplicate proof document for every gate.

| Gate / milestone | Result | Evidence |
| --- | --- | --- |
| Rust pinned build (WF632) | PASS | [Rust reference replay and build provenance](rust-reference-replay.md) |
| Rust Balance reference reproduction (WF633) | PASS, standalone only | [Exact DPS and settings](rust-reference-replay.md) |
| Go native parity P7.1.2 | OPEN | No passing evidence |
| Live gsim 2D parity P7.1.3 | OPEN | No passing evidence |
| Rust balanced RNG / hit tables | Historical CI snapshot — not a current gate verdict | [WF636 Actions run](https://github.com/dosibjrn/mage-level-sim/actions/runs/40898989538) |
| Go and Rust source/build artifact packaging | Historical CI snapshot — not a current gate verdict | [Source + executable CI](https://github.com/dosibjrn/mage-level-sim/actions/runs/40900014618) |

## Rust-reproduced Balance P7.1 — owner accepted

[Owner decision](druid-p7/README.md) · [P7.1 evidence and exact Rust input/output](druid-l60-balance/p7.1/README.md) · [WF633 raw files](wf633/README.md). Balance P7.1 was explicitly closed by owner on a Rust replay. **Native Go and live gsim-2D integrations remain separately unverified by these Rust artifacts.** For the **current** certified-checkpoint total, use the [live M1 scoreboard](../../README.md#m1--verified-progress-over-time), not a historical snapshot. [Current work allocation](../planning/WORK_PRIORITY.md).

**Current P7.5 requirements:** see the [owner-approved P7 contract](../gates/P7.md), including 99% of both the pinned external reference and strongest accepted-compatible prior, independent 1,000-fight stochastic final holdout, search budget, legality and live world↔native causality. This historical evidence index does not define or override acceptance thresholds.
