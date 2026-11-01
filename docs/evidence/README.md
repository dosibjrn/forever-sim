# Evidence index

Every gate promoted to `main` must have a validated evidence directory here, linked in the top-level [README](../../README.md). Files should carry stable functional names without manual version suffixes. Git commits preserve history.

| Gate / milestone | Result | Evidence |
| --- | --- | --- |
| Rust pinned build (WF632) | PASS | [Rust reference replay and build provenance](rust-reference-replay.md) |
| Rust Balance reference reproduction (WF633) | PASS, standalone only | [Exact DPS and settings](rust-reference-replay.md) |
| Go native parity P7.1.2 | OPEN | No passing evidence |
| Live gsim 2D parity P7.1.3 | OPEN | No passing evidence |
| Rust balanced RNG / hit tables | Historical CI snapshot — not a current gate verdict | [WF636 Actions run](https://github.com/dosibjrn/mage-level-sim/actions/runs/40898989538) |
| Go and Rust source/build artifact packaging | Historical CI snapshot — not a current gate verdict | [Source + executable CI](https://github.com/dosibjrn/mage-level-sim/actions/runs/40900014618) |

## Required content of a passing gate's evidence directory

Keep the input request, version-locked engine and database provenance, exact talents and complete gear/enchant IDs, buffs/debuffs, consumes, rotations/APL, seed and iteration count, build commands, output logs and validation reports. Include gear alternatives and optimizer traces where the gate covers search, and independent stochastic holdout where required. A summary alone does not qualify for gate certification.

## Rust-reproduced Balance P7.1 — owner accepted

[Owner decision](druid-p7/README.md) · [P7.1 evidence and exact Rust input/output](druid-l60-balance/p7.1/README.md) · [WF633 raw files](wf633/README.md). Balance P7.1 was explicitly closed by owner on a Rust replay. **Native Go and live gsim-2D integrations remain separately unverified by these Rust artifacts.** Fully certified P1–P7 checkpoints: **0/148**. [Current work allocation](../planning/WORK_PRIORITY.md).

**P7.5 acceptance (PROCESS v2.10, issue #10):** the numeric PASS statistic is the **mean DPS** from a frozen independent >=1,000-fight stochastic holdout versus `max(full saved reference, 0.99 × strongest accepted compatible P7.1–P7.4 stochastic mean)`; **no one-sided 95% CI lower-bound criterion**. Verify accepted prior provenance, same pinned source/engine/encounter/RNG/scoring, legality, <=300s cold search and true world↔native causal trace separately. Historical unverified P7.4 scores cannot become the comparator merely by appearing in a successful CI log.
