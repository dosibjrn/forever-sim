# Repository structure — maintained ideal architecture

**Owner: Clean.** This is the single maintained **target architecture**, not a description of code that has already migrated. The 2026-11-03 owner decisions [#357](https://github.com/dosibjrn/forever-sim/issues/357) and [#359](https://github.com/dosibjrn/forever-sim/issues/359) supersede the earlier long-term GameIR, Python source-legality and separate world-executor targets. [AUTONOMOUS_AGENTS](planning/AUTONOMOUS_AGENTS.md) defines roles; [WORK_PRIORITY](planning/WORK_PRIORITY.md) and owned issues carry execution priority.

**Authority and compatibility:** [OVERALL_PLAN](../OVERALL_PLAN.md), [PROCESS](../PROCESS.md) and the [gate contracts](gates/README.md) still govern scope and acceptance. A target-state design does not itself change an approved gate, disallow a currently approved pinned Go path, invalidate historical evidence or authorize an untested removal. Keep existing working production paths until their required behavior is proved through the native replacement.

## Ideal architecture (end state)

The project is a **scenario and optimization client** of one source-of-truth game engine: the maintained, upstream-synchronized and **exact-SHA-pinned MythicSim Rust fork**. This logical map describes responsibility boundaries; named target folders need not exist yet.

```text
/
├── README.md                     # short overview, launchers and canonical links
├── OVERALL_PLAN.md / PROCESS.md  # owner-controlled WHAT / HOW
├── run.sh / run.ps1              # retained stable launch interfaces
├── .github/workflows/            # bounded native/CI/on-demand gate jobs
├── config/
│   ├── validation/               # checkpoint matrix and scenario settings
│   └── gates/                    # gate policy, NOT Warcraft rules
├── integrations/
│   └── mythicsim-rust/
│       └── engine/               # tested immutable fork SHA (git submodule)
├── src/
│   ├── scenarios/                # our encounter/world/leveling scenario requests [target]
│   ├── engine_client/            # thin typed native request/result/refusal transport [target]
│   ├── optimization/             # generic candidate mutation, search, paid scoring [target]
│   ├── shared/                   # narrowly scoped backend-neutral primitives [target]
│   └── service/                  # optional user/API presentation
├── tools/                         # stable gate/diagnostic CLIs, including wf_gate.py
├── scripts/commands/             # shell/PowerShell operator wrappers
├── tests/
│   ├── generic/                  # search/scoring contracts
│   ├── integration/              # native↔world↔optimizer behavior [target]
│   ├── gates/                    # formal selected-production gate execution
│   ├── fixtures/                 # immutable test-only scenarios
│   ├── maintenance/              # layout, import and workflow integrity
│   └── release/                  # explicitly requested slow tests
└── docs/
    ├── INDEX.md
    ├── REPOSITORY_STRUCTURE.md   # this maintained target
    ├── gates/                    # approved acceptance predicates
    ├── evidence/                 # retained reference/replay evidence
    ├── planning/
    │   ├── WORK_PRIORITY.md
    │   ├── AUTONOMOUS_AGENTS.md
    │   └── M1_PASSES.tsv         # Merge-only acceptance ledger
    └── reference/                # historical cited sources when needed for evidence
```

`src/shared/` is a permanent but intentionally small home for **backend-neutral primitives only**: reusable arithmetic/data structures whose behavior does not encode Warcraft facts, source acquisition, class/spec rules, talent or gear legality, combat/world semantics, or scenario policy. Examples include numeric field transforms, stateless math, pure identifier normalization and stable queue mechanics; callers own the facts, policy and provenance. It is not a catch-all and does not bless every current file beneath the directory. In particular, the live `leveling/` and `talents/` subpackages remain transitional migration inputs, as recorded below.

Game spell, rank, talent, gear, enchant, race/class/level/phase legality, acquisition, buffs, combat effects and **game-world execution** belong to the pinned MythicSim Rust fork, including interfaces required for movement, 2D feedback, chainpull and persistent 100-mob behavior. The client defines *which scenario to evaluate*, proposes candidate configurations, calls native validation/preparation/execution, and scores/optimizes actual native results. It may retain provenance and scenarios, not a second game-facts authority or a renamed GameIR. If native coverage is missing, extend and test the fork; do not infer source absence from an unsupported-native refusal.

Native game data and legality **do not** have a permanent `data/forever/`, `src/game/data/forever/`, `src/rulesets/` or Python GameIR home in this target. Existing folders remain **temporary live migration inputs**, with actual consumers and acceptance history protected until replaced. The `integrations/mythicsim-go/` reference and older gsim workflows likewise remain as long as approved PROCESS compatibility and active callers require them; this target is not authorization to break them.

## Dependency and ownership rules

1. **One game truth:** upstream + Forever patch changes are integrated into the maintained Rust fork, tested there and promoted by reviewed exact submodule SHA. Only that fork defines Warcraft mechanics, source legality and legal build options. No independent source index, acquisition database, class/rank eligibility tables, game-rule validator or Python combat-engine fallback is a permanent client component.
2. **One native request boundary:** scenario + proposed build/APL → native capability and legality validation (including structured invalid vs unsupported reasons) → genuine native execution and causal world events/ACK → paid results → generic optimizer. Preserve balanced RNG and independent stochastic final validation where PROCESS requires them. Neither fabricated event ACKs nor surrogate DPS-as-leveling satisfy the gates.
3. **No separate world-gameplay truth:** spatial/world, chainpull, recovery and persistent combat semantics mandated by active P3–P7.5 must survive inside or through the selected MythicSim interface. Current Python 2D and gsim components are transitional working paths; move consumers first, verify both positive and negative native cases, and only then remove duplicated execution.
4. **Public CLI and process stability:** `python tools/wf_gate.py --class ... --level ... --gate ...`, `run.sh`, `run.ps1`, approved gates and the Merge-only `M1_PASSES.tsv` remain stable throughout migration. No extra source-authority CLI namespace, gate-only simulator, duplicated acceptance registry or unnecessary hourly heavy CI.
5. **Tests and evidence reflect real boundaries:** run scoped unit/integration tests for a moved consumer, plus the required selected-production native/world gate path where behavior is affected. Existing accepted PASS receipts persist; no silent invalidation or invented new PASS from compilation/metadata. Keep only replay evidence still required by current acceptance or referenced decisions.
6. **Small meaningful boundaries:** live code grouped by scenario, native client, generic optimizer and service, not numbered experiments. Move modules when their actual callers and tests can move together. Delete obsolete working-tree code once proven unused; Git history is the archive.

## Current main deviations and concrete migration checks

These are **observed current paths**, not proof that any one of them is safe to delete:

| Current state | Required migration before removal |
| --- | --- |
| `src/game/model/ir.py` defines GameIR; `src/game/data/forever/registry.py` and `source_ir_assembly.py` produce and enrich it | Trace every runtime, optimizer, gate, CLI and test caller; expose the actual missing Rust data/behavior and migrate callers to native requests before deleting schema, providers and overlays |
| Legacy P1/P2 providers and probes | P1 runtime/diagnostic stack removed by #706; active P3-P6 callers decoupled from the retired P2 source-profile provider by #702. Both gates are retired from acceptance, public CLI and M1; historical diagnostics are not live migration prerequisites |
| `src/v2/source_budgeted_level_route.py` and `src/v2/source_bounded_route_evidence.py` remain transitional GameIR/Python L2 route and replay paths. #688 removed route acquisition-proof vetoes; #697 retired the old reader flag; #696 deleted the acquisition-proof subsystem; #707 removed duplicate validation passes. These are not active P3-P7.5 gate providers | Work1 owns the remaining native route candidate/score migration. Preserve route continuity, 2D ACK, persistent resources, chainpull, 100-target behavior and stable CLI; do not restore Forever acquisition proof |
| `src/game/runtime/`, `src/v2/`, `src/rulesets/` and flat legacy `src/` execute or reference earlier semantics | Trace active entry points, tests and held-out obligations; migrate one safe real consumer at a time, retaining required 2D ACK, 100-mob continuity and stable CLI behavior while MythicSim owns game legality |
| `src/shared/leveling/objective.py` retains transitional hit-chance helpers; expected cycle scoring is owned by `src/optimization/leveling_score.py`, and the canonical CMaNGOS Classic-proxy target HP input is scenario-owned in `src/scenarios/leveling_targets.py`. `src/shared/leveling/spaced_pulls.py` remains a compatibility re-export for the active Work2 native-world caller. `src/shared/talents/tree.py` still evaluates talent eligibility from Python rule maps. Deterministic 2D pack geometry lives in `src/scenarios/spaced_pulls.py` | These are live migration inputs, not permanent common primitives. Move game-rule facts and talent legality to MythicSim Rust, and move any still-needed pure scoring math to `src/optimization/`; retain each caller until its replacement is exercised with focused regressions |
| `data/forever/`, `gate_sources/`, `gate_evidence/`, `state/`, `evidence/` hold overlapping source, working-state and proof material | Preserve any required historical gate reference/replay, then remove duplicated live game-data ownership only after native authority is proven; generated transient state can be ignored where safe |
| Flat `tools/` and `tests/` contain long-lived and numbered one-off code | Group by real responsibility, update direct-entrypoint/CI/pytest references, and prove behavior before deleting or moving; file counts are not a goal |

This table is a migration boundary map, **not a parallel backlog or an exhaustive caller inventory**. The live issue-level inventories and handoffs belong to [#357](https://github.com/dosibjrn/forever-sim/issues/357), [#359](https://github.com/dosibjrn/forever-sim/issues/359), and [WORK_PRIORITY](planning/WORK_PRIORITY.md).

## Convergence rules — Clean's repeated work loop

1. Compare fresh `main`, current owned issue/PR and this target. Continue the existing unfinished cleanup, selecting one bounded actual dependency or code-removal delta. Do not create hypothetical blockers or a second inventory document.
2. Prove callers and compatibility **before deleting or moving**: production imports, command/CI paths, live source/ruleset contracts, active agent branches, held-out/replay obligations and accepted evidence. Don't call a legacy name proof of dead code.
3. Move one real consumer to a working native interface, then remove only the duplicated code made dead by that migration. Avoid expanding the old GameIR or replacing it with a renamed Python rules engine. Do not take Work1/Work2's active gameplay fixes.
4. Verify the changed boundary with focused regressions and a real production path when needed. Docs-only target corrections need link/contract review, not invented gate PASSes.
5. Deliver one small PR stating the observed deviation, exact paths migrated/deleted, validation and `M1 affected gates:` line. Merge integrates; only Merge records actual M1 gate progress. Preserve stable launchers and canonical docs; delete obsolete history instead of adding an archive tree.
6. Interrupt for proven shared CI/runner/build breakage only; fix the real cause and resume the architecture migration. A useful existing bounded GitHub Action may run between cycles; avoid repeated heavy acceptance for unchanged behavior.

**Progress means fewer live competing game-rule sources and verified native consumers, not more reports or fewer files for their own sake.** Git history retains completed migrations.