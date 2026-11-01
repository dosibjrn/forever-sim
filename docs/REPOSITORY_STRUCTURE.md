# Repository structure — maintained ideal architecture

**Owner: Clean.** This is the **one canonical target-state architecture** for `dosibjrn/forever-sim`. It describes the structure we are converging to, not a claim that the current tree already matches it. Clean maintains this vision in `main`, delivers safe incremental cleanup PRs, and changes the vision only when an architectural decision genuinely changes. Current ownership/work priorities are in [AUTONOMOUS_AGENTS](planning/AUTONOMOUS_AGENTS.md) and [WORK_PRIORITY](planning/WORK_PRIORITY.md).

**Non-negotiables:** approved [OVERALL PLAN](../OVERALL_PLAN.md), [PROCESS](../PROCESS.md), and [gate contracts](gates/README.md) take precedence. The repo must support source-grounded 9-class × 4-level × profile checkpoints, genuine engine/world causality, paid 100-mob evaluation and separately required P7 MythicSim reference evidence. Repo neatness is not permission to delete a required test, source, formal gate proof, existing valid user decision, or stable entry point.

## Ideal architecture (end state)

One place for each responsibility. This is a **logical layout**: names marked “target” are migration destinations, not existing paths that can be imported today.

```text
/
├── README.md                   # short product overview, first commands, links
├── OVERALL_PLAN.md             # approved product scope; owner-controlled
├── PROCESS.md                  # approved process; owner-controlled
├── run.sh / run.ps1            # stable end-user launch interfaces
├── .github/workflows/          # focused, bounded reproducible CI
├── config/
│   ├── validation/             # static 148-checkpoint configuration
│   └── gates/                  # static gate applicability/policies [target]
├── data/forever/               # pinned source observations and canonical catalogues
├── src/
│   ├── game/
│   │   ├── data/              # source parsing and compiled source-backed GameIR
│   │   ├── model/             # legal game identities/models and state contracts
│   │   ├── runtime/           # persistent world, actor, pull, travel, recovery
│   │   └── search/            # unified gear × talents × policy search [target]
│   ├── rulesets/              # explicit Classic/Forever ruleset adapters
│   └── service/               # optional service/API/UI presentation
├── integrations/
│   ├── mythicsim-rust/        # pinned Rust combat integration and diagnostics
│   └── mythicsim-go/          # pinned Go combat integration and diagnostics
├── tools/                      # canonical Python public CLI: gate, ingest, audit
├── scripts/
│   ├── commands/             # shell/PowerShell operator wrappers
│   └── diagnostics/          # narrowly scoped developer tooling
├── tests/
│   ├── generic/              # cross-class search/runtime/publication contracts
│   ├── mechanics/            # class-specific behavior contracts
│   ├── integration/          # source→engine→world→recovery tests [target]
│   ├── gates/                # live gate CLI and acceptance tests [target]
│   ├── fixtures/             # test-only immutable inputs
│   ├── maintenance/          # layout, CI and hygiene safety checks
│   └── release/              # explicitly invoked slow tests
└── docs/
    ├── INDEX.md              # small navigation index
    ├── REPOSITORY_STRUCTURE.md # this maintained vision, no separate design plan
    ├── gates/                 # approved normative gate contracts
    ├── evidence/              # formal gate evidence, pinned repro inputs/results
    ├── planning/
    │   ├── WORK_PRIORITY.md  # one mutable work queue and agent ownership
    │   └── AUTONOMOUS_AGENTS.md # one maintained agent role contract
    └── reference/            # necessary retained external/source reference notes
```

**Not intended as permanent top-level responsibility islands:** `gate_config/`, `gate_sources/`, `gate_evidence/`, `fixtures/`, `state/`, historical `evidence/`, root coverage JSON/TXT, migration one-offs. These currently exist. Their contents need classification and **proof of consumer migration before movement/removal**; the ideal map does not authorize blindly deleting or relocating them. `docs/archive/` is not a destination for new obsolete files. Git history retains deleted history.

## Architecture and dependency rules

1. **Game facts flow in one direction:** pinned `data/forever/` → source ingestion/compiled GameIR + rulesets → legal models → actual persistent world/actor state + selected MythicSim combat backend → paid evaluation/recovery/scoring → **one generic** optimizer → formal gate/CLI and user-facing presentation. Avoid circular dependencies and multiple competing source/legality/scoring paths.
2. **One authoritative mechanic and one real execution path per selected engine.** Rust is preferred and Go is valid when pinned, as governed by PROCESS. The source catalogue describes facts; the engine performs implemented native combat effects; world owns world/actor continuity. No fake effect ACK, surrogate DPS-as-leveling proxy, class-specific winner presets or hidden whitelists.
3. **One implementation of shared abstractions.** New reusable gear/talent/policy/recovery behavior belongs in the generic domain, not parallel class-specific optimizers. Class/ruleset adapters provide sourced deltas, not duplicated engines. Old `src/v2/`, `src/classic_mage_leveling_optimizer_v10.py` and legacy state must be assessed by **actual callers, benchmark/held-out challenger obligations and parity tests** before removal; never equate their age with safe obsolescence.
4. **A predictable entry point.** Python public commands live under `tools/` (especially stable `python tools/wf_gate.py --class ... --level ... --gate ...`), shell/PS wrappers under `scripts/commands/`, root launchers remain stable. Keep long-lived code out of numbered one-off scripts; do not create a third CLI namespace.
5. **Tests mirror boundaries** and invoke real source/runtime for the behavior under test. Fast tests by default; slow formal gate, 100-mob and holdout runs intentionally scoped. No disabling tests to make layout changes pass.
6. **Separate data, test fixtures, operational state and proof.** `data/forever/` is source/canonical catalogue; `tests/fixtures/` is immutable test-only input; live-generated transient state should be reproducible and gitignored where safe; `docs/evidence/` holds actual PROCESS-required acceptance evidence. Never merge diagnostic result into a PASS or delete an artifact without confirming no gate/replay depends on it.
7. **Small stable root and short docs.** Root files are only stable entry points and project governance/config. README links to a small set of maintained canonical docs. Avoid per-folder readmes with duplicated process rules, one-time handoff reports, checklists that only repeat GitHub issues, and parallel “v2-final-new” authority files.

## Current deviations worth removing

These are **observed categories** from public main inspection, **not** a claim that their individual files are all obsolete.

| Present state | Desired improvement | Safety check before deleting/moving |
| --- | --- | --- |
| `src/` has many flat legacy modules; `src/v2/` is large | Group by concrete domain boundary; converge on one generic production path | Import graph, actual runtime callers, benchmarks and backward compatibility |
| Very large `tests/` and `tools/` roots | Group tests by behavior and tools by stable responsibility; remove superseded one-off entry points | Pytest collection, invoked workflows, imports, CLI compatibility |
| `gate_config/`, `gate_sources/`, `gate_evidence/`, `fixtures/` | Consolidate static config, source inputs, formal proof and test fixtures into their intended homes | Search every path consumer and update CLI defaults/tests/evidence references together |
| `evidence/` and `docs/evidence/` coexist | Retain canonical formal proof; delete/replace redundant historical raw artifacts when no consumers | PROCESS evidence requirements, accepted historical decisions, replay pointers |
| `state/`, coverage reports and migration scripts tracked | Keep only required reproducible fixtures/source; ignore generated noise; delete completed migration tooling | Verify no runtime startup, test or required replay depends on tracked artifacts |
| `docs/archive/` and long historical narrative in guides | Git history is the archive; retain only currently useful explanations | Preserve current normative instructions and valid reference links |
| Multiple wrappers/engines/optimizer layers | Clarify real ownership and remove redundant duplicate code paths | Source-native behavior, persistent world ACK, paid scoring and independent gate replays |

## Convergence rules — Clean's repeated work loop

1. **Compare `main` against this target**, then the current Clean-owned issue/PR. Pick **one bounded high-impact deviation**; continue the same unfinished cleanup until integrated rather than starting another survey.
2. **Prove obsolete before delete:** check all references, active PRs, callers, source ownership, retention needs and accepted gate evidence. Obsolete items are deleted from the working tree, not shuffled into a new `legacy/` or `archive/` directory.
3. **Migrate by responsibility, not aesthetics:** move a live file only when the new home has a clearer owner. Update imports, workflow paths, scripts, tests and docs in the same change. Preserve exported public CLIs or provide tested compatibility during migration.
4. **Prove safe:** focused test collection and behavioral checks at the changed boundary; exercise a real production path when it could be affected. Never call a structure-only check a formal checkpoint pass.
5. **Deliver a small PR** referencing the particular gap this closes, observed actual change and passing scoped checks. Merge agent integrates it. Repeat; update this target vision only for a substantive architecture decision.
6. **Interrupt only for immediate cross-agent friction** (CI/runner failures, broken shared paths, duplicate critical implementation). Fix the root cause and return to the structural roadmap. Coordinate around Work1/Work2/Prio-owned branches; architecture cleanup must not stall the 0/148 → 1/148 critical path.

**Definition of architectural progress:** fewer live competing abstractions and dead files, clearer responsibilities, fewer surprise paths and simpler real development flows, **without** reducing source fidelity, acceptance evidence or runtime coverage. File counts may help find waste but are not a target metric; avoid performative inventory and mandatory reports.

## Grounded baseline and navigation

On 2026-11-02 the checked `main` root includes `src/`, `tests/`, `tools/`, `scripts/`, `integrations/`, `data/`, `docs/`, `config/`, `state/`, `evidence/`, `gate_config/`, `gate_sources/`, `gate_evidence/`, `fixtures/` and root coverage artifacts. `src/game/` already has model/data/runtime partitions; `tests/generic/`, `tests/mechanics/`, `tests/maintenance/`, and `tests/release/` exist. These are starting points, not the goal's completion.

See [README](../README.md) for entry points, [docs index](INDEX.md) for normative docs, [evidence index](evidence/README.md) for formal gate proof, and [work queue](planning/WORK_PRIORITY.md) for live ownership. Completed historical migration steps and obsolete directory manifests belong in Git history, not expanded here.
