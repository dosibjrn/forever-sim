# WoW Forever — simulator and optimizer

**Fully certified P1–P7 checkpoints evidenced in this repo: 0/148.** User-accepted P7 subgates are tracked separately; do not mistake them for full P1–P7 checkpoint certification. A green CI job or a standalone reference replay does not certify P1–P7.

## Work queue and the 148-checkpoint matrix

**Fully certified P1–P7 checkpoints: 0 / 148.** Four levels **20, 30, 40 and 60** × (9 unrestricted classes + 4 Druid profiles + 24 other profiles) = **37 per level**. Level 50 is **not** in the approved 148-checkpoint scope.

| Level | Unrestricted | Druid spec profiles | Other class spec profiles | Total |
| --- | ---: | ---: | ---: | ---: |
| 20 | 9 | 4 | 24 | 37 |
| 30 | 9 | 4 | 24 | 37 |
| 40 | 9 | 4 | 24 | 37 |
| 60 | 9 | 4 | 24 | 37 |
| **Total** | **36** | **16** | **96** | **148** |

**Combat executor policy:** MythicSim **Rust preferred, Go equally valid**, with one selected pinned engine per compatible gate chain and live gsim-2D integration whenever mandated by PROCESS. Build PASS is not gameplay PASS.

**Next small work item:** [Druid L60 Balance P7.2 — rotation-only discovery](docs/WORKER.md). The owner has accepted **Balance P7.1 via exact Rust-input/Rust-engine replay**, and **Feral Cat P7** by explicit approval; see [recorded decision](docs/evidence/druid-p7/README.md) and [full Rust input/output](docs/evidence/druid-l60-balance/p7.1/README.md). These owner decisions are not evidence of Go-native or live 2D tests, and do not increase the 0/148 count.

**Balance Druid L60 P7.3:** [WF663 native Rust talent search and frozen 4,000-fight holdout](docs/evidence/druid-l60-balance/p7.3/WF663_ACCEPTANCE.md) — 729.388 DPS, 7,255 paid candidates, 263 s. Native search PASS by the recorded result; full gsim-2D↔Rust causal gate remains **NOT CERTIFIED**. 

**P7 DPS floors:** P7.1 reproduces the exact external reference; **P7.2–P7.4 may be within 1% below that same reference**; P7.5 still must reach the **full external reference** and at least 99% of the strongest compatible prior P7 winner (>=1,000 independently frozen stochastic fights, **mean DPS**, no 95% confidence-bound PASS requirement; only accepted compatible prior winners count). This changes no search budget or causal evidence requirement.

**Gate order within a checkpoint:** P1 abilities → P2 talents → P3 gear smoke → P4 independent cold 30 s search → P5 cold 300 s → P6 100-mob saturation replay → P7.1 reference → P7.2 rotation → P7.3 talents → P7.4 gear → P7.5 joint search. The historical overall checkpoint priority is Druid L20 → Druid L30 → Mage L30; the mutable milestone plan controls future execution order.

**Work and promotion:** worker implements **one formal gate per branch**, commits tests/results under [docs/evidence](docs/evidence/README.md); integrator reviews and merges accepted gates into `main`. No incomplete gate code should reach `main`. Canonical approved [PROCESS.md](PROCESS.md) is v2.9 and [OVERALL_PLAN.md](OVERALL_PLAN.md) is v5; the Git history contains earlier versions.

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
| [`tools/`](tools/README.md) | Existing Python gate/capture/ingest/audit entry points |
| [`data/`](data/) | Forever source snapshots, catalogues and staged databases |
| [`docs/`](docs/INDEX.md) | Canonical documentation map, active evidence, reference and archive |
| [`docs/evidence/`](docs/evidence/README.md) | Curated accepted gate decisions, reproducible requests/results and build proof |
| [`evidence/`](evidence/README.md) | Historical WF experiments; **not** the current PASS scoreboard |
| `gate_config/`, `gate_sources/`, `gate_evidence/` | Operational gate policy, source inputs and machine evidence; paths still used by code |

**[Large assets and Git LFS migration](docs/LARGE_ASSETS_LFS.md)** — binary catalogues, large historical JSON and source archives; tracked blobs require an authenticated LFS conversion before claiming migration.

**[Full directory audit, owners and safe cleanup roadmap](docs/REPOSITORY_STRUCTURE.md).** The numerous shell/PowerShell launchers are a separate [small, test-required cleanup](https://github.com/dosibjrn/mage-level-sim/issues/14); `run.sh` and `run.ps1` remain stable root entry points.

## Gate scoreboard and evidence

| Gate / engineering milestone | Status | Evidence |
| --- | --- | --- |
| Go pinned native Linux build (WF637) | **PASS — build only** | [Build logs, source and binary checksum](docs/evidence/go-native-build/README.md) |
| Rust BalancedRNG compile and smoke (WF636) | **PASS — build only** | [CI and 50-fight test, known limits](docs/evidence/rust-balanced-build/README.md) |
| Rust pinned engine build (WF632) | **PASS** | [Build, pinned commit and artifact](docs/evidence/rust-reference-replay.md) |
| Rust 10,000-iteration Balance reference replay (WF633) | **PASS — standalone** | [Settings, gear, raid buffs, DPS parity, limitations](docs/evidence/rust-reference-replay.md) |
| Druid Feral Cat — P7 | **CLOSED — user approved** | [Decision and evidence gaps](docs/evidence/druid-p7/README.md) |
| Druid Balance — P7.2 (WF641, 1% tolerance) | **CLOSED — user approved** | [300s search, 2,000-fight holdout, technical exceptions](docs/evidence/druid-l60-balance/p7.2/README.md) |
| Druid Balance — P7.1 | **CLOSED — user approved** | [Rust reference evidence and remaining raw evidence](docs/evidence/druid-p7/README.md) |
| Native Go P7.1.2 full reference parity | **OPEN** | No passing evidence |
| Live gsim 2D integration P7.1.3 | **OPEN** | No passing evidence |
| Rust probability-balanced RNG (including hit tables) | **IN PROGRESS** | [WF636 CI](https://github.com/dosibjrn/mage-level-sim/actions/runs/40898989538) |
| Complete P1–P7 checkpoint certification | **0/148 PASS** | [PROCESS](PROCESS.md) |

### Evidence contract

For **each passing gate**, commit a self-contained folder under `docs/evidence/<gate-or-checkpoint>/` with the exact source revision, input requests, item/gear/talent IDs, buffs/debuffs/consumes, build commands and binary hashes, full logs/raw results, statistics, acceptance validator output, and independent holdout as applicable. README links to the folder's `README.md`. Missing evidence = OPEN/FAIL, never inferred PASS. Binary CI artifacts may remain in GitHub Actions if the evidence includes a durable source revision and build/run link; preserve text logs and inputs under Git when practical.

Per [PROCESS](PROCESS.md), promote **each individually accepted gate** to `main` after verifying its evidence. Do not mix unaccepted work into a passing merge. Git handles document history: use canonical [PROCESS.md](PROCESS.md) and [OVERALL_PLAN.md](OVERALL_PLAN.md), without filename versioning.

---

Historical WF464 README material is preserved in [Git history](https://github.com/dosibjrn/mage-level-sim/blob/8ff66bab8ee5259e6dc76f291452b2f36ac5d4c6/README.md); it is not current gate evidence.
