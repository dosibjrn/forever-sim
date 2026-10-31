# Repository structure — ownership, compatibility and migration-safe target

**Status:** provisional navigation/cleanup plan during public migration P0 [#25](https://github.com/dosibjrn/forever-sim/issues/25). This is **not** a claim that the source/data baseline is complete, that any refactor has occurred, or that a P1–P7.5 checkpoint passed. Approved [PROCESS v2.10](../PROCESS.md) and [OVERALL PLAN v5](../OVERALL_PLAN.md) remain authoritative and unchanged. Work ordering is owned by [WORK_PRIORITY](planning/WORK_PRIORITY.md).

## Observed public main (2026-10-31)

Inspected **`5ad52793e9ef48b7628685f3b07adefbec0ea664`** via the Git tree and selected file contents. The tree has **59 entries including directories** and is an **incomplete migration snapshot**, not the canonical final inventory.

| Present path | Verified present contents / responsibility | Limit |
| --- | --- | --- |
| `src/` | Python class/engine registries, build/context code; `src/game/` checkpoint modules and a source-acquisition helper; `src/v2/` finalist helper | Missing most historical GameIR/world/runtime/optimizer modules |
| `integrations/mythicsim-go/` | World-boundary ingress Go files | Not proof of an integrated native executor |
| `integrations/mythicsim-rust/` | Python native gear/joint-search/matrix adapters and three adapter tests | Not proof of a runnable pinned Rust engine |
| `tools/` | `wf_gate_p1_live.py`, `wf_gate_p2_live.py`, `wf_gsim_go_live_range_probe.py` | Approved `tools/wf_gate.py` CLI is **absent** from this partial main |
| `scripts/` | P0 snapshot and branch-port helpers | Administrative/migration scripts, not production simulator modules |
| `docs/` | `planning/WORK_PRIORITY.md`, `migration/BRANCH_INVENTORY.md` | Curated evidence/docs are not yet restored |
| `.github/workflows/` | Manual source-restore and runner-smoke workflows | No production CI or gate-green inference |
| Root | `README.md`, `PROCESS.md`, `OVERALL_PLAN.md`, `run.sh`, `run.ps1`, `pytest.ini`, metadata | Launchers currently refer to `src.master_optimizer` and `src.listener`, which are **absent** from this partial tree |

The historical private **read-only** source has a `docs/REPOSITORY_STRUCTURE.md` describing `tests/`, `data/`, `evidence/`, `gate_config/`, `gate_sources/`, `gate_evidence/`, `config/`, `state/`, and `scripts/commands/`. Those paths are **not** present in the inspected public main. Historical path counts, completed cleanup claims, and older PROCESS version references must be revalidated against the *restored public main* before being repeated as current facts.

## Target ownership (design, not a move plan yet)

Prefer existing paths and working imports over cosmetic symmetry. **Do not create empty directories or relocate modules merely to match this table.**

| Stable home | Single primary responsibility | Dependency / compatibility rule |
| --- | --- | --- |
| `src/game/` and existing `src/` packages | Source-derived GameIR/rulesets, executable actor and 2D world state | Source facts enter via versioned readers; world owns geometry, native owns supported combat mechanics; avoid circular engine imports |
| `integrations/mythicsim-rust/`, `integrations/mythicsim-go/` | Pinned native engine adapters, event bridge, full event→world ACK and native next decision | Native ↔ world boundary is explicit and causally tested; Rust preferred, Go valid; no duplicate damage/resource ownership |
| Existing optimizer modules under `src/` | Generic gear × talents × APL/pull/recovery search and paid 100-mob evaluator | Consume a shared executor/score interface, never separate synthetic DPS or class-specific winner paths |
| `tests/` (when restored) | Unit, source legality, negative-control, integration and acceptance regressions | Preserve pytest discovery, imports, Windows/Unix paths and explicit release-only tests |
| `data/`, `fixtures/` or `tests/fixtures/` (when restored) | Immutable/pinned source catalogues versus deliberately small test fixtures | Preserve source provenance and original SQLite/LFS **bytes**; don't merge fixtures with runtime output |
| `config/`, `gate_config/`, `gate_sources/`, `gate_evidence/` (when restored) | Static config, gate inputs and machine-generated verdicts respectively | Keep distinct until all path readers, CLI defaults and acceptance registry are mapped and tested |
| `tools/` | Stable Python command/gate entry points | **Preserve** `python tools/wf_gate.py --class ... --level ... --gate ...` and evidence contract |
| `scripts/`, `scripts/commands/` (when restored) | Migration, maintenance and secondary shell/PowerShell wrappers | **Preserve** root `./run.sh` and `./run.ps1`; validate both OS families before any relocation |
| `docs/`, `docs/evidence/` (when restored) | Governance navigation, curated reproducible accepted gate evidence | Only machine-verifiable, source/runtime-pinned gate evidence may change checkpoint counts |
| `evidence/`, `state/` (when restored) | Historical WF raw experiments and mutable run state | **Not** current PASS ledger; do not delete or rename while hard-coded readers remain |
| `.github/workflows/` | Focused, exact-HEAD verification | Public manual runner-smoke first; no CI fan-out or zero-step rerun spam during P0 |

### Intended dependency direction

Pinned **source/data → source legality + GameIR → actor/native + 2D world event protocol → persistent paid evaluator → generic search → gate validation and evidence**. Documentation and CI consume those outputs; they must not redefine simulation semantics. This is a responsibility boundary, **not** a statement that current imports already follow it. Trace real import edges after P0 and refactor only when a tested dependency cycle or maintainability defect warrants it.

## P0-safe execution and handoff

1. **DO FIRST — P0 owner:** finish audited, history-free public source/data/LFS migration [#25](https://github.com/dosibjrn/forever-sim/issues/25), verify file/path hashes and hydrated SQLite/LFS payloads, then manual public runner-smoke. This guide must not be used to call the partial tree runnable.
2. **DO NEXT — Clean:** compare the restored `docs/REPOSITORY_STRUCTURE.md` (including the historical private guide) with this proposal. The migration's `rsync` currently does **not** protect this documentation path, so a source snapshot can overwrite it. Reconcile the two in a **separate reviewed documentation PR** after P0; keep only one canonical guide. Do not silently overwrite historical notes.
3. **DO THEN — Clean:** inventory actual module imports, CLI consumers, test fixture references, evidence registry readers, and workflow path filters on a pinned restored main. Document a *specific* high-value dependency/compatibility defect before proposing any move.
4. **Only if beneficial:** one bounded structural PR at a time, with exact-HEAD Linux/Windows launcher and Python import/pytest tests, relevant Go/Rust builds, fixture/path and evidence-schema checks. Merge belongs to Merge-agent. Preserve other agents' `work/*` branches.

### Explicit non-goals while P0 is partial

No bulk `src/` reshuffle, no data/SQLite/LFS pruning, no `evidence/` renaming, no new CI triggers, no speculative gate promotions, no changes to `PROCESS.md`, `OVERALL_PLAN.md` or Prio-agent's `WORK_PRIORITY.md`. A smaller directory count is not progress toward **148/148** unless it reduces verified engineering risk or critical-path time.
