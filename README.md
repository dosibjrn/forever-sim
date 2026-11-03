> **Migration status (2026-11-01): COMPLETE.** [Public P0 issue #25](https://github.com/dosibjrn/forever-sim/issues/25) records the pinned audited source publication: 1,877 permitted paths published from 1,914 tracked private paths, with 37 intentionally protected. [Independent public checkout and LFS hydration](https://github.com/dosibjrn/forever-sim/actions/runs/41255246045) succeeded with 13/13 snapshot tests; 11 SQLite and three large JSON LFS payloads were hydrated. Legacy private auto-trigger workflows remain excluded deliberately. `dosibjrn/mage-level-sim` is historical read-only source. **This is not an active P3–P7.5 checkpoint acceptance; current M1 certification is shown in the live chart below.**

# WoW Forever — simulator and optimizer

**Engine ownership and migration:** The approved end state is **one game-rules authority: the exact-SHA-pinned [MythicSim Rust fork](https://github.com/dosibjrn/mythicsim-forever-engine)**. Rust owns Warcraft source facts, build legality, combat mechanics and game-world execution. Forever defines scenarios, proposes and searches candidates, scores native results and verifies the unchanged gate contracts. Python GameIR, source catalogues, Go/gsim bridges and Python world code in the **current** tree are transitional live dependencies, not additional permanent sources of game truth; migrate their real consumers and verify native replacement before deleting them. See [#357](https://github.com/dosibjrn/forever-sim/issues/357), [#359](https://github.com/dosibjrn/forever-sim/issues/359) and the [target architecture](docs/REPOSITORY_STRUCTURE.md).


## M1 — historical progress and current active scope

![Historical pre-v2.20 11-gate M1 acceptance and diagnostic partial progress](docs/planning/M1_HISTORY.svg)

**Historical chart:** this SVG shows the former 11-gate scope through 2026-11-03 and is not comparable to the current scope. PROCESS v2.20 retires P1/P2; active acceptance is P3–P6 and P7.1–P7.5 (1,332 pairs across 148 checkpoints). Merge will regenerate the chart on the next official M1 publication. The certified checkpoint count remains separate; incomplete or incompatible active-gate results do not certify a checkpoint.

The [M1 ledger](docs/planning/M1_PASSES.tsv) is the only measurement source. Its Git history supplies the timestamps. Each [Merge-launched on-demand gate run](.github/workflows/m1-on-demand-record.yml) that improves the recorded results updates the ledger **and this chart together** on main. No chart-only scheduling, synthetic progress, or independent status records.

## Upstream inspiration and acknowledgments

This is an independent Forever simulation and optimization research project. The combat execution and reference-parity work builds on **[MythicSim](https://www.mythicsim.com/wow-forever)** and its open-source [Rust Forever engine](https://github.com/sage3648/mythicsim-forever-engine) and [Go reference fork](https://github.com/sage3648/mythicsim-forever-engine-go). Thanks to the MythicSim and WoWSims contributors for the engines, mechanics research, reference results, and open tooling.

**Credit and scope:** this repository is not the official MythicSim project and is not affiliated with its maintainers. Engine references and pinned versions must remain traceable; upstream licenses and notices govern any adapted code.

**Fully certified active-gate checkpoints are counted in the M1 ledger.** The linked SVG is the pre-v2.20 11-gate history until Merge regenerates it. User-accepted P7 subgates are tracked separately; do not mistake them for full active P3–P7.5 checkpoint certification. A green CI job or a standalone reference replay does not certify the active P3–P7.5 checkpoint.

## Work queue and the 148-checkpoint matrix

**Fully certified active-gate checkpoints: 0/148 at the last recorded main-ledger read; run `python tools/m1_progress.py` for the current nine-gate scoreboard.** Four levels **20, 30, 40 and 60** × (9 unrestricted classes + 4 Druid profiles + 24 other profiles) = **37 per level**. Level 50 is **not** in the approved 148-checkpoint scope.

| Level | Unrestricted | Druid spec profiles | Other class spec profiles | Total |
| --- | ---: | ---: | ---: | ---: |
| 20 | 9 | 4 | 24 | 37 |
| 30 | 9 | 4 | 24 | 37 |
| 40 | 9 | 4 | 24 | 37 |
| 60 | 9 | 4 | 24 | 37 |
| **Total** | **36** | **16** | **96** | **148** |

**Current approved execution policy:** MythicSim **Rust preferred, Go equally valid** under PROCESS, with one selected pinned engine per compatible gate chain and live gsim-2D integration wherever required. The Rust-only target architecture does not silently remove an approved Go path or existing causal world requirement. Build PASS is not gameplay PASS.

**Current critical path:** [live native→world event/HP/hash/ACK→next decision (public #7)](https://github.com/dosibjrn/forever-sim/issues/7) and [source-paid persistent 100-mob evaluation (public #19)](https://github.com/dosibjrn/forever-sim/issues/19), as ordered by [WORK_PRIORITY](docs/planning/WORK_PRIORITY.md). Historical P7 diagnostics follow; they are not the current implementation queue. The owner has accepted **Balance P7.1 via exact Rust-input/Rust-engine replay**, and **Feral Cat P7** by explicit approval; see [recorded decision](docs/evidence/druid-p7/README.md) and [full Rust input/output](docs/evidence/druid-l60-balance/p7.1/README.md). These owner decisions are not evidence of Go-native or live 2D tests, and do not automatically increase certified-checkpoint counts.

**Balance Druid L60 P7.3:** [WF663 native Rust talent search and frozen 4,000-fight holdout](docs/evidence/druid-l60-balance/p7.3/WF663_ACCEPTANCE.md) — 729.388 DPS, 7,255 paid candidates, 263 s. Native search PASS by the recorded result; full gsim-2D↔Rust causal gate remains **NOT CERTIFIED**. 

**P7 DPS floors (owner-approved 2026-11-02):** P7.1–P7.4 require at least **99% of the pinned saved reference** after 1,000 stochastic final iterations. P7.5's independently frozen 1,000-fight stochastic holdout mean must reach **93% of the greater of the saved reference and the strongest accepted-compatible P7.1–P7.4 result**. Internal candidate search uses deterministic balanced RNG; neither that score nor a confidence lower bound substitutes for final stochastic mean DPS. The search budgets, source/engine identity and live world↔native causality requirements are unchanged; [P7 contract](docs/gates/P7.md) is authoritative.

**Active gate order within a checkpoint:** P3 gear smoke → P4 independent cold 30 s search → P5 cold 300 s → P6 100-mob saturation replay → P7.1 reference → P7.2 rotation → P7.3 talents → P7.4 gear → P7.5 joint search. The historical overall checkpoint priority is Druid L20 → Druid L30 → Mage L30; the mutable milestone plan controls future execution order.

**Implementation and acceptance:** develop and merge focused, regression-tested production improvements incrementally. Run expensive active P3–P7.5 acceptance only when ready; P1/P2 are retired and must not be reintroduced. Merge alone records genuine PASS timestamps in the canonical M1 ledger. The authoritative requirements are [PROCESS.md](PROCESS.md), [gate predicates](docs/gates/README.md) and [OVERALL_PLAN.md](OVERALL_PLAN.md).

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

| Current path | Current purpose / migration status |
| --- | --- |
| [`src/`](src/) | Scenario/search/scoring/service code plus **transitional** Python GameIR, ruleset and world-runtime callers; no permanent second game-mechanics authority |
| [`tests/`](tests/README.md) | Unit, regression, integration and acceptance tests (currently mostly flat) |
| [`tools/`](tools/) | Python gate/capture/ingest/audit entry points |
| [`data/`](data/) | Retained source snapshots, catalogues and staged databases needed by current callers/evidence during native migration |
| [`docs/`](docs/INDEX.md) | Canonical documentation map, accepted reference evidence and source notes |
| [`docs/evidence/`](docs/evidence/README.md) | Curated accepted gate decisions, reproducible requests/results and build proof |
| [`evidence/`](evidence/README.md) | Historical WF experiments; **not** the current PASS scoreboard |
| `config/gates/`, `gate_sources/`, `gate_evidence/` | Static gate applicability policy, source inputs and machine evidence |

**[Large assets and Git LFS migration](docs/LARGE_ASSETS_LFS.md)** — binary catalogues, large historical JSON and source archives; public LFS payloads were hydrated in an independent checkout; do not mistake pointer files for hydrated bytes.

**[Clean-owned ideal repository architecture and convergence rules](docs/REPOSITORY_STRUCTURE.md).** The numerous shell/PowerShell launchers are a completed [historical private-repo launcher cleanup](https://github.com/dosibjrn/mage-level-sim/issues/14); `run.sh` and `run.ps1` remain stable root entry points.
