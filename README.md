> **Migration status (2026-11-01): COMPLETE.** [Public P0 issue #25](https://github.com/dosibjrn/forever-sim/issues/25) records the pinned audited source publication: 1,877 permitted paths published from 1,914 tracked private paths, with 37 intentionally protected. [Independent public checkout and LFS hydration](https://github.com/dosibjrn/forever-sim/actions/runs/41255246045) succeeded with 13/13 snapshot tests; 11 SQLite and three large JSON LFS payloads were hydrated. Legacy private auto-trigger workflows remain excluded deliberately. `dosibjrn/mage-level-sim` is historical read-only source. **This is not a P1–P7.5 checkpoint acceptance; current M1 certification is shown in the live chart below.**

# WoW Forever — simulator and optimizer


## M1 — verified progress over time

![M1 verified acceptance and diagnostic partial progress](docs/planning/M1_HISTORY.svg)

**Green:** genuine accepted P1–P7.5 gate PASSes out of 1,628. **Amber:** best measured partial-inclusive diagnostic progress (not an accepted PASS). Fully certified checkpoints out of 148 are shown separately; incomplete or incompatible gate results do not certify a checkpoint. The vertical scale is zoomed to visible progress, not 0–100%.

The [M1 ledger](docs/planning/M1_PASSES.tsv) is the only measurement source. Its Git history supplies the timestamps. Each [Merge-launched on-demand gate run](.github/workflows/m1-on-demand-record.yml) that improves the recorded results updates the ledger **and this chart together** on main. No chart-only scheduling, synthetic progress, or independent status records.

## Upstream inspiration and acknowledgments

This is an independent Forever simulation and optimization research project. The combat execution and reference-parity work builds on **[MythicSim](https://www.mythicsim.com/wow-forever)** and its open-source [Rust Forever engine](https://github.com/sage3648/mythicsim-forever-engine) and [Go reference fork](https://github.com/sage3648/mythicsim-forever-engine-go). Thanks to the MythicSim and WoWSims contributors for the engines, mechanics research, reference results, and open tooling.

**Credit and scope:** this repository is not the official MythicSim project and is not affiliated with its maintainers. Engine references and pinned versions must remain traceable; upstream licenses and notices govern any adapted code.

**Fully certified P1–P7 checkpoints are counted in the live M1 chart above.** User-accepted P7 subgates are tracked separately; do not mistake them for full P1–P7 checkpoint certification. A green CI job or a standalone reference replay does not certify P1–P7.

## Work queue and the 148-checkpoint matrix

**Fully certified P1–P7 checkpoints: see the M1 chart above.** Four levels **20, 30, 40 and 60** × (9 unrestricted classes + 4 Druid profiles + 24 other profiles) = **37 per level**. Level 50 is **not** in the approved 148-checkpoint scope.

| Level | Unrestricted | Druid spec profiles | Other class spec profiles | Total |
| --- | ---: | ---: | ---: | ---: |
| 20 | 9 | 4 | 24 | 37 |
| 30 | 9 | 4 | 24 | 37 |
| 40 | 9 | 4 | 24 | 37 |
| 60 | 9 | 4 | 24 | 37 |
| **Total** | **36** | **16** | **96** | **148** |

**Combat executor policy:** MythicSim **Rust preferred, Go equally valid**, with one selected pinned engine per compatible gate chain and live gsim-2D integration whenever mandated by PROCESS. Build PASS is not gameplay PASS.

**Current critical path:** [live native→world event/HP/hash/ACK→next decision (public #7)](https://github.com/dosibjrn/forever-sim/issues/7) and [source-paid persistent 100-mob evaluation (public #19)](https://github.com/dosibjrn/forever-sim/issues/19), as ordered by [WORK_PRIORITY](docs/planning/WORK_PRIORITY.md). Historical P7 diagnostics follow; they are not the current implementation queue. The owner has accepted **Balance P7.1 via exact Rust-input/Rust-engine replay**, and **Feral Cat P7** by explicit approval; see [recorded decision](docs/evidence/druid-p7/README.md) and [full Rust input/output](docs/evidence/druid-l60-balance/p7.1/README.md). These owner decisions are not evidence of Go-native or live 2D tests, and do not automatically increase certified-checkpoint counts.

**Balance Druid L60 P7.3:** [WF663 native Rust talent search and frozen 4,000-fight holdout](docs/evidence/druid-l60-balance/p7.3/WF663_ACCEPTANCE.md) — 729.388 DPS, 7,255 paid candidates, 263 s. Native search PASS by the recorded result; full gsim-2D↔Rust causal gate remains **NOT CERTIFIED**. 

**P7 DPS floors:** P7.1 reproduces the exact external reference; **P7.2–P7.4 may be within 1% below that same reference**; P7.5 still must reach the **full external reference** and at least 99% of the strongest compatible prior P7 winner (>=1,000 independently frozen stochastic fights, **mean DPS**, no 95% confidence-bound PASS requirement; only accepted compatible prior winners count). This changes no search budget or causal evidence requirement.

**Gate order within a checkpoint:** P1 abilities → P2 talents → P3 gear smoke → P4 independent cold 30 s search → P5 cold 300 s → P6 100-mob saturation replay → P7.1 reference → P7.2 rotation → P7.3 talents → P7.4 gear → P7.5 joint search. The historical overall checkpoint priority is Druid L20 → Druid L30 → Mage L30; the mutable milestone plan controls future execution order.

**Implementation and acceptance:** develop and merge focused, regression-tested production improvements incrementally. Run expensive P1–P7.5 acceptance only when ready; Merge alone records genuine PASS timestamps in the canonical M1 ledger. The authoritative requirements are [PROCESS.md](PROCESS.md), [gate predicates](docs/gates/README.md) and [OVERALL_PLAN.md](OVERALL_PLAN.md).

## Command launchers

Keep the stable root entry points `./run.sh` and `./run.ps1`. Less common
validation, release/listener smoke, service-control and source-capture wrappers
are in [`scripts/commands/`](scripts/commands/README.md) (issue #14 phase 2A).
For example: `bash scripts/commands/run-validation-fast.sh`.
The `run-fast`, `run-both`, `run-v2`, `run-forever` and `run-mc` variants
are in [`scripts/commands/`](scripts/commands/README.md) (issue #14 phase 2B).
For example: `bash scripts/commands/run-fast.sh --optimize-only` or
`pwsh -File scripts/commands/run-forever.ps1 -NoListener`.
The root `run.sh` and `run.ps1` remain unchanged stable entry points.

## Find your way around

| Where | What belongs there |
| --- | --- |
| [`src/`](src/) | Python GameIR, rulesets, 2D world, optimizers and local services |
| [`tests/`](tests/README.md) | Unit, regression, integration and acceptance tests (currently mostly flat) |
| [`tools/`](tools/) | Python gate/capture/ingest/audit entry points |
| [`data/`](data/) | Forever source snapshots, catalogues and staged databases |
| [`docs/`](docs/INDEX.md) | Canonical documentation map, accepted reference evidence and source notes |
| [`docs/evidence/`](docs/evidence/README.md) | Curated accepted gate decisions, reproducible requests/results and build proof |
| [`evidence/`](evidence/README.md) | Historical WF experiments; **not** the current PASS scoreboard |
| `gate_config/`, `gate_sources/`, `gate_evidence/` | Operational gate policy, source inputs and machine evidence; paths still used by code |

**[Large assets and Git LFS migration](docs/LARGE_ASSETS_LFS.md)** — binary catalogues, large historical JSON and source archives; public LFS payloads were hydrated in an independent checkout; do not mistake pointer files for hydrated bytes.

**[Clean-owned ideal repository architecture and convergence rules](docs/REPOSITORY_STRUCTURE.md).** The numerous shell/PowerShell launchers are a completed [historical private-repo launcher cleanup](https://github.com/dosibjrn/mage-level-sim/issues/14); `run.sh` and `run.ps1` remain stable root entry points.
