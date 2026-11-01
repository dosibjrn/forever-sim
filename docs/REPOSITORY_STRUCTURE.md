# Repository structure — current ownership and migration guide

This is a **navigation and maintenance guide**, not a replacement for the approved [PROCESS](../PROCESS.md) or [OVERALL PLAN](../OVERALL_PLAN.md). The counts below are tracked Git blobs from the **public `main` tree at `d87380c8` (2026-11-01)**, not live counters. P0 source/data/LFS migration is complete under [public issue #25](https://github.com/dosibjrn/forever-sim/issues/25), with [independent LFS checkout and 13/13 snapshot tests](https://github.com/dosibjrn/forever-sim/actions/runs/41255246045); full checkpoint certification remains **0/148**. Historical *private-repository* issue #14 covered launcher relocation phases 2A/2B; public issue #14 is a **different** native/world integration issue. A folder's location does not confer a gate PASS.

## Current repository map

| Path | Tracked files | Ownership / status | Safe next step |
| --- | ---: | --- | --- |
| `src/` | 388 | Production Python runtime. `game/` = generic GameIR and world/runtime, `rulesets/` = class/ruleset implementations, `v2/` = legacy/current analytic optimizer code, `service/` = local services | Keep as-is while changing engine backends; refactor by import-safe subsystem with tests |
| `tests/` | 668 | Growing test suite, with `release/` (explicit slow tests) and `maintenance/` (root launcher, release-layout and SQLite hygiene contracts) | Organize remaining tests incrementally; audit imports, explicit CLI targets and relative paths before moving |
| `tools/` | 293 | Existing Python command entrypoints and support files (capture, ingest, gates, audit, validation) | Classify; do not break `python tools/wf_gate.py` or internal imports by moving blindly |
| `scripts/` | 47 | Auxiliary launchers under `commands/`, diagnostics, migration/maintenance and benchmarks | Keep administrative/non-library scripts here; disentangle from Python CLI `tools/` later |
| `docs/` | 79 | Documentation, the **curated formal evidence index**, planning/reference/archive | Keep docs here; archive obsolete handovers, link certified evidence from README |
| `evidence/` | 239 | Historical WF raw runs, logs and prior-work evidence; **not the active gate ledger** | Leave paths stable until known hard-coded consumers are migrated; see [evidence archive note](../evidence/README.md) |
| `data/` | 49 | Wow Forever data, source captures, SQLite catalogues, staged legacy DBs (about 72 MB) | Audit generated DBs/journals vs canonical source before deduplication; never invent item mechanics |
| `state/` | 46 | Historical optimizer/runtime state and snapshots | Treat as runtime state / checkpoint snapshots; move only with reproducible migration + tests |
| `config/` | 1 | Current 148-checkpoint metadata `config/validation/checkpoint_148.json` | Remains the natural home for static gate/validator configurations |
| `gate_config/` | 1 | P1 scenario applicability policy (`p1_scenario_applicability_v1.json`) | Candidate for `config/gates/`, **only after path consumers verified** |
| `gate_sources/` | 2 | Druid P2 source catalogue/RED input artifacts | Keep distinct from gate verdicts and static config; relocation requires importer/test audit |
| `gate_evidence/` | 2 | Machine-generated Druid P2 gate verdict JSON; the current gate CLI defaults here | Do not move until CLI option/default and tests have migrated |
| `fixtures/` | 1 | Historical held-out Druid L20 build | Candidate for `tests/fixtures/` after search for absolute/relative path consumers |
| `tests/release/` | 2 | Explicit release-only suite (migrated from `release_tests/`); normal pytest collection skips this folder | Run with `scripts/commands/run-release-smoke.sh` or direct `pytest -q tests/release` |
| `integrations/` | 57 | MythicSim Go world-boundary overlays and Rust native diagnostics/search adapters; pinned engines are external | Add Rust/Go adapters here only as real runnable integrations with pinned revisions |
| `.github/` | 2 | Public workflow definitions; retain controlled triggers and exact-HEAD evidence | Extend acceptance CI incrementally; green compilation is not a P7 PASS |

Directory counts are **tracked files**; they include some historical outputs. Other small root-level files include `README.md`, `PROCESS.md`, `OVERALL_PLAN.md`, `VERSION`, `pytest.ini`, entry scripts and an old coverage report.

## Responsibility boundaries and dependency direction

The **target direction** below is an architecture rule for future small changes, **not a claim that every existing import already obeys it**. No production paths are being moved by this guide.

| Boundary | Current concrete location | Allowed responsibility / next dependency |
| --- | --- | --- |
| Pinned source and fixtures | `data/forever/`, `gate_sources/`, `tests/fixtures/`, `fixtures/` | Source facts and test inputs feed GameIR; do not infer a game mechanic from an optimizer result |
| GameIR, rulesets, world | `src/game/model/`, `src/game/data/`, `src/rulesets/`, `src/game/runtime/` | Source-backed rules and world geometry/state; the world owns position, pulls and movement |
| Combat native boundary | `integrations/mythicsim-go/world_boundary/`, `integrations/mythicsim-rust/` | Selected pinned MythicSim Go/Rust owns implemented combat effects; exchange explicit timed events and applied-world ACK, never synthetic receipts |
| Search and scoring | `src/game/policy_search.py`, `src/game/talent_search.py`, `src/v2/` | Evaluate legal candidates against the selected live runtime; `src/v2/` is a legacy/analytic challenger, not automatic gate authority |
| Gate and CLI adapters | `tools/wf_gate.py`, `tools/`, `scripts/`, `run.sh`, `run.ps1` | Public invocations orchestrate and validate, not invent engine mechanics or substitute stored evidence for execution |
| Tests and verdicts | `tests/`, `integrations/mythicsim-rust/tests/`, `docs/evidence/`, `gate_evidence/` | Tests assert behavior; runtime evidence and formal verdicts must carry exact source/ruleset/engine/trace identity |

**Intended flow:** pinned source → source-legal GameIR/ruleset → persistent 2D world + selected native combat session (shared clock, native event → applied world HP/hash → full ACK → next native decision) → continuous paid recovery and 100-mob evaluator → reusable gear × talents × APL search → gate validator and independently reproducible evidence. The Go `world_boundary.go` explicitly labels range receipts as *not* world-damage ACK; the native→world proof is still tracked under [public issue #7](https://github.com/dosibjrn/forever-sim/issues/7), and the paid evaluator under [public issue #19](https://github.com/dosibjrn/forever-sim/issues/19). Neither is certified by directory placement.

**Compatibility invariants:** preserve `./run.sh`, `./run.ps1`, `python tools/wf_gate.py --class ... --level ... --gate ...`, the existing `gate_config/` / `gate_sources/` / `gate_evidence/` paths and the evidence contract. Do not reparent imports, rename test fixtures or redirect native engines without exact-HEAD import/CLI, Linux/Windows, Rust/Go and gate-regression proof. See [current priorities](planning/WORK_PRIORITY.md) before starting a layout-only PR.

## Evidence: three distinct responsibilities

1. **Accepted gate and backend-build evidence:** `docs/evidence/<checkpoint>/<gate>/` or `docs/evidence/<engineering-milestone>/`, indexed from [README](../README.md) and [evidence index](evidence/README.md). Must include actual run configurations, executable/source/revision hashes, full logs or outputs and a verifiable decision.
2. **Historical research/reproduction evidence:** `evidence/wf*/` (including legacy logs and artifacts). This is an archive, **not an automatic PASS registry**. `src/game/checkpoint_acceptance_status.py` currently reads some files in this tree by exact path.
3. **Machine-generated acceptance inputs / outputs:** `gate_sources/`, `gate_evidence/`, `gate_config/`. These are operational paths, **not duplicate docs directories**. `tools/wf_gate.py` defaults `--evidence-dir` to `<repo>/gate_evidence`.

Never rename or merge these directories to make them visually uniform without updating the real readers and regression tests.

## Root launcher cleanup — issue #14 phase 2A

Auxiliary wrappers for validation (`run-validation-*`), release/listener smoke,
service start/stop and Wowhead/talents capture now live in
[`scripts/commands/`](../scripts/commands/README.md), with tested repo-root
resolution regardless of invoking working directory. The original 19 root wrappers were removed in phase 2A; phase 2B moves 10
alternate `run-*` launchers into the same directory. This leaves 10 root files,
including the two unchanged primary `run.sh` / `run.ps1` entry points.

This is a path migration for auxiliary entrypoints. Consumers of their former
root paths must use the new `scripts/commands/` paths. Phase 2B has also been performed; any remaining external callers need compatibility review. The phase 2A tests exercise Bash wrappers
with a harmless Python stub and parse PowerShell on Windows rather than
starting services or browsers in CI.

## Release-only test isolation

`tests/release/` replaces the separate `release_tests/` directory without
changing which tests run by default. `pytest.ini` excludes the directory from
implicit recursion, while explicit `pytest tests/release` still collects both
release modules. Bash/PowerShell smoke wrappers point to the new directory.
A focused test verifies both collection modes in an isolated miniature suite.

## Root launcher cleanup — issue #14 phase 2B

Ten alternate Bash/PowerShell launchers (`run-fast`, `run-both`, `run-forever`,
`run-v2`, `run-mc`) now live under [`scripts/commands/`](../scripts/commands/README.md).
They resolve repository root relative to themselves, and `run-both` / `run-mc`
retain calls to the unchanged primary entry points. Bash stubbed invocation
and Windows PowerShell parser tests protect the migration; external callers
must update old paths.

## What should stay at the top level

- `README.md` — concise start page: purpose, status **0/148**, currently accepted subgates, next gate, entry points and directory navigation.
- `PROCESS.md` — canonical approved formal gate contract (**v2.10**).
- `OVERALL_PLAN.md` — canonical approved product goal (**v5**).
- `src/`, `tests/`, `tools/`, `config/`, `data/`, `docs/`, `integrations/`, `.github/` — meaningful software directories.
- `run.sh` and `run.ps1` — existing compatibility entry points (don't move without a tested replacement).
- `VERSION`, `pytest.ini` — standard project metadata.

Long-term desirable consolidation: move auxiliary CLI wrappers into `scripts/` or `bin/`, place static gate configuration under `config/gates/`, move test fixtures under `tests/fixtures/`, move acceptance-specific test suites into `tests/acceptance/`, and archive or ignore generated runtime state and SQLite `-wal` / `-shm` *only after inspecting actual consumers*. The layout above is a **target**, not a claim that the moves have happened.

## Small, independently reviewable work items

1. **Root launcher cleanup** — [historical private issue #14](https://github.com/dosibjrn/mage-level-sim/issues/14). Phases 2A/2B relocate auxiliary and alternate launchers; preserve root `./run.sh` / `./run.ps1`. Legacy coverage reports remain a separately audited optional move.
2. **Gate config & evidence consolidation** — identify every reference to `gate_config`, `gate_sources`, `gate_evidence` and `config/validation`; introduce a resolver/compatibility tests; move **one** class of files in a separate branch.
3. **Fixture and acceptance test consolidation** — release-only modules live in `tests/release/` (excluded from default pytest discovery); next audit the standalone `fixtures/` reader and move only after path-consumer validation.
4. **Tools/tests hierarchy** — independently classify the 293 tracked `tools/` paths and 668 tracked `tests/` paths. Start with a single narrow functional group and preserve public CLI/module imports; do **not** wholesale rename hundreds of files.
5. **Source data/state provenance** — distinguish canonical Wowhead source, generated catalogue DBs, staged snapshots and runtime outputs. SQLite transient `-wal`/`-shm` sidecars were removed from version control after checking the WAL was zero bytes; real SQLite catalogues remain tracked and unchanged. Next audit genuine staged database redundancy separately.

For every migration: one branch → list all moved paths and readers → minimal edits → runnable relevant regression tests → approved PR → integrator merge to `main`. Do not bundle these migrations with a P7 gate implementation.

## Test suite: generic publication and route navigation

Seven generic source-registry, all-class decision publication and native
route-navigation regressions (`G47–G48d`) were moved byte-for-byte into
[`tests/generic/publication/`](../tests/generic/publication/README.md).
The normal `pytest.ini` collection includes the group; the tests do not use
test-file-relative fixtures or imports from `tests.*`. Source inspections
retain the existing repository-root working directory. A layout-only
contract guards the paths without adding another Actions workflow.
This migration does not award any P1–P7 checkpoint PASS.

## Test suite: generic search and CI trigger hygiene

Seven existing generic search/frontier, gear sensitivity, fixed-point and
mode/policy regression modules moved byte-for-byte to
[`tests/generic/search/`](../tests/generic/search/README.md). Their source
inspections and catalogue checks use repository-working-directory-relative
paths, so normal root-invoked pytest collection is preserved. No simulator
source or formal gate evidence changed.

CI path filters were tightened: the generic class/runtime layout jobs now
trigger for their own grouped test paths rather than **every**
`tests/test_generic_*.py` change. Root launcher smoke no longer runs just
because `README.md` or this maintenance guide changed; launcher scripts,
their tests and the workflow itself still trigger it. This reduces
irrelevant workflow runs without disabling the actual tests or changing
gate-runtime validation ownership.

## Test suite: generic class adapters

Fifteen existing generic Druid, Hunter, Mage, Priest, Rogue, Shaman, Warlock,
Warrior and Bear policy tests were moved byte-for-byte into
[`tests/generic/classes/`](../tests/generic/classes/README.md). The tests
continue to read `src/` and catalogue paths relative to the repository
working directory, not relative to their own files; no test body or runtime
code changed. The normally collected class group has a focused layout and
collection contract; these checks do not certify P1–P7.

## Test suite: generic combat runtime

Twelve event, autoattack, resource, recovery, multi-actor and summon tests
were moved byte-for-byte from flat `tests/` to
[`tests/generic/runtime/`](../tests/generic/runtime/README.md). Several tests
inspect `src/game/runtime/*.py` by root-relative path; the pytest invocation
working directory remains repository root. The modules do not use test-file
relative fixtures, and all existing test assertions remain unchanged.
A scoped collection contract and targeted workflow protect the relocation.
No production engine or gate-contract files changed.

## Test suite: Druid mechanics

Twenty-seven Druid spell, talent-schema, gear, form, rage, recovery and source
regression modules were moved **byte-for-byte** into
[`tests/mechanics/druid/`](../tests/mechanics/druid/README.md).
They have absolute package imports and no test-relative filesystem paths.
The historical skipped oracle test stays skipped, without changing its status.
Default pytest collection still includes these tests. The migration's narrow
CI proves discovery and lightweight mechanics behavior only, **not** P1–P7.

## Test suite: Paladin mechanics

Ten existing Paladin spell, source-fidelity, runtime SQLite, and equipment
selection regression modules have been moved byte-for-byte to
[`tests/mechanics/paladin/`](../tests/mechanics/paladin/README.md).
The files use absolute source-package fixture roots and need no relative
path changes; `pytest.ini` continues collecting them by default.
No production runtime or P1–P7 verdict is modified.

## Test suite: Hunter mechanics

Fourteen existing Hunter unit/regression modules were moved byte-for-byte
from the flat test root to [`tests/mechanics/hunter/`](../tests/mechanics/hunter/README.md).
They cover pet focus/families, talent legality, real gear and post-20 profile
fidelity. No test assertions, engine code, sources or P1-P7 gate evidence were
modified. Normal pytest discovery still includes the directory; a focused
collection contract and optional targeted regressions are provided by CI.

## Test suite: Mage mechanics

An initial seven Ice Lance, Ice Barrier, Frostbite/Shatter and periodic-crit
tests and another sixteen Mage engine, gear, talent/rotation, scoring and UI
regressions have been moved **byte-for-byte** into
[`tests/mechanics/mage/`](../tests/mechanics/mage/README.md). Their imports
remain absolute from `src/`, and the normal `pytest.ini` discovery includes
the nested directory. No P1–P7 acceptance evidence or engine code changed.

## Test suite: maintenance contracts

Four existing repository-maintenance regression modules moved from the flat
`tests/` root into [`tests/maintenance/`](../tests/maintenance/README.md):
root launcher phases 2A/2B, opt-in release collection, and SQLite sidecar
hygiene. They are **included in normal pytest collection**, unlike the
explicit-only `tests/release/` suite. Root resolution changed only from
`Path(__file__).resolve().parents[1]` to `parents[2]`; all existing assertions
are unchanged. The three targeted Actions workflows were updated to their new
paths. A directory-layout smoke test guards the move.

## SQLite generated sidecar cleanup

The tracked `data/forever/catalogue/items_2026-09-29.sqlite-wal` (empty) and
`items_2026-09-29.sqlite-shm` (32 KiB) were removed from Git and patterns for
SQLite WAL/SHM/rollback-journal sidecars added to `.gitignore`. These are
SQLite-generated companions, not catalogue source of truth; SQLite regenerates
them if required. **No `.sqlite` database, source capture, snapshot or LFS
pointer was deleted or modified.** Do not mistake removing sidecars for a Git
LFS migration or approval to remove staged databases.

## Quick navigation

- [Project README](../README.md)
- [Approved PROCESS](../PROCESS.md)
- [Approved OVERALL PLAN](../OVERALL_PLAN.md)
- [Worker contract and next gate](WORKER.md)
- [Gate and engineering evidence](evidence/README.md)
- [Old WF handovers](archive/README.md)
