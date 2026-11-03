# FOREVER SIM — one production path to M1 (148/148)

**Mutable execution strategy / Prio-owned.** Normative product: [OVERALL_PLAN v5](../../OVERALL_PLAN.md) (do not rewrite). Normative acceptance: [PROCESS](../../PROCESS.md) and the active [P3–P7.5 predicates](../gates/README.md). Current assignments: [WORK_PRIORITY](WORK_PRIORITY.md). Implementation failures and decisions: [issue #131](https://github.com/dosibjrn/forever-sim/issues/131) and existing owner issues. **No second strategy, progress plan, evidence tree or gate-only simulator.**

## The one implementation we are building

```text
canonical Forever source + class/level/profile + objective
   -> legal gear, talent, ability and policy candidates
   -> ONE shared whole-build optimizer
   -> ONE paid production evaluator
        -> selected genuine pinned MythicSim Rust/Go combat
        -> real continuous gsim 2D world / movement / recovery where required
   -> real measured performance and behavior
   -> thin on-demand assertions for P3–P6 and P7.1–P7.5
```

**P1 and P2 are retired as formal acceptance gates.** No standalone ability-effect gate, talent-rank gate, P1/P2 provider, M1 row or hidden replacement proof is required. This does not remove spell, talent, rank or combat functionality: MythicSim remains the game-rules authority, and the optimizer must still generate and evaluate the actual legal candidate space needed by the remaining gates.

**148 are input checkpoints, not 148 implementations.** P3 calls the production gear scorer; P4/P5 call the same legal optimizer with independent cold 30/300-second budgets and genuine 100-mob results; P6 independently replays those winners; P7.1–P7.5 call the real native+2D evaluator on the separate pinned MythicSim reference, including low-repeat deterministic balanced-RNG searches and the final frozen 1,000-stochastic-fight reference/holdout. P7.1–P7.4 final floor is **0.99 × saved reference DPS**; P7.5 final floor is **0.93 × max(saved reference DPS, strongest accepted-compatible prior)**. Never substitute gsim-only, raw native-only, a source inventory, CI green or a wrapper for a hybrid acceptance requirement. Keep all remaining numeric and source/engine criteria.

## Critical-path sequence

1. **First contact:** for one likely-nearest checkpoint (currently Druid L60 Balance), attempt the nine active production-facing gate entry points, checking prerequisites cheaply before heavy work. Record the first actual missing production operation for each. A missing CLI provider is not proof that its scorer, optimizer or world runtime is missing. Do not spend cycles on retired P1/P2 gate work.
2. **Fix the longest true dependency:** Work1 continues native↔real 2D causal execution/P7.1.3 [#7](https://github.com/dosibjrn/forever-sim/issues/7). Work2 continues one paid 100-mob source-legal optimizer/replay [#19](https://github.com/dosibjrn/forever-sim/issues/19), [#15](https://github.com/dosibjrn/forever-sim/issues/15). Prio resolves only demonstrated shared native interface/capability blockers and wires thin calls to production where a real function already exists. Do not reset ongoing owner branches or build nine independent gate engines.
3. **First vertical 9/9:** run each active gate once when genuinely runnable; correct actual RED→GREEN defects and retain successful PASS timestamps. A checkpoint is certified only when all nine active gates are mutually compatible under PROCESS. Get 0/148 → 1/148 without relaxing anything.
4. **Demonstrate genericity:** execute the same code and gate functions for a materially different class AND level (e.g. a pet class at L20 versus Druid L60) and fix generic effect/source failures rather than adding class-specific winners.
5. **Scale to 148:** populate the canonical source/legality and 148 input configurations, run on-demand PASSes across them, and focus on missing production behavior, not new adapters. Revalidate an old PASS only on material invalidation.

**Reason this minimizes total time:** the native/world engine and paid optimizer are shared prerequisites to many remaining gates and classes, so parallel work on them has compounding returns. Do not polish retired gates in isolation while P7 cannot execute. No repeated surveys, parallel engines or recurring heavy acceptance CI.

## Automatic M1 measurement

M1 has **148 × 9 = 1,332** approved checkpoint-gate pairs.

- **M1 passed gate executions:** `N/1332`, `100*N/1332 %`; a row is added only by the actual live gate runner returning PASS. A missing/blocked/failed gate contributes zero to strict PASS count; a genuinely executed FAIL or P7 objective BLOCKED run may earn a separately labeled noncertifying PARTIAL.
- **Fully certified checkpoints:** `C/148`, only when all nine active gate PASSes for the same checkpoint are mutually compatible under PROCESS. Nine rows with absent/inconsistent compatibility provenance are a candidate, not a certified checkpoint.
- **Inside a failing gate:** actual executed `verified/applicable` behaviors/slots, percentage and optional Pareto work model. A full PASS is one; a partial is diagnostic only. For P7, use actual selected native↔2D DPS / required DPS instead of fake simulation-count denominators. Unknown source scope is marked provisional.
- **Optional continuous M1 progress index:** `(full PASS gates + sum(actual partial gate coverage fractions)) / 1332 × 100%`. This is a descriptive diagnostic estimate, not certified `N/1332` acceptance. For example, if nothing else has passed and Druid L20 P4 is verified at 3/25, the index is `(3/25)/1332 × 100 ≈ 0.0090%`, while accepted gates remain `0/1332`. Record partials only from actual on-demand production execution, not inventories or mocks.

The minimal implementation is the existing `tools/wf_gate.py`, `tools/m1_progress.py` and the same flat `docs/planning/M1_PASSES.tsv` with accepted PASS stamps or genuine measured PARTIAL fractions. After an actual source-backed on-demand acceptance run:

```sh
python tools/wf_gate.py --class druid --level 60 --spec balance --gate P3 --record-pass
python tools/m1_progress.py
```

**Automatic script-owned results:** Work1/Work2/Prio/Clean identify `M1 affected gates: class:level:spec:gate ...` in each implementation PR. Merge deduplicates the list and only launches the trusted GitHub Action with `/m1-run ...` on an already merged PR; it does not hand-grade PASS/FAIL or manually copy numbers. Actions runs the real `wf_gate.py --record-progress`, records genuine PASS or eligible executed PARTIAL in the one TSV on `main`, and updates the scoreboard. A measured P7 coupled live DPS can be provisional PARTIAL even if a distinct UI/acceptance requirement leaves the gate BLOCKED. P4/P5 may measure sourced ability execution in completed paid runtime screens without pretending one short probe is the 30/300-second full gate. No synthetic count from 1,000 fight samples, provider existence, gear-slot visits or source-only inventory is allowed.

**Monotonic partial display:** one gate row holds its best previously measured comparable fraction; a lower subsequent outcome remains visible in Actions logs as a regression/scope-change warning, not a silent drop in the historical progress index. A changed denominator never gains credit merely by discarding previously verified behaviors. FULL PASS supersedes partial; only material invalidation removes an accepted PASS. A 100% measured subcomponent is still only PARTIAL if another active gate predicate fails.

**Compatibility is fail-closed.** A passing live provider must supply trustworthy common source/ruleset/executor compatibility identity before nine independent stamps may yield automatic 1/148. Do not invent this field merely to move the number. The stamp is an audit record of executed code, not a substitute for execution.

### 80/20 means effort interpretation, never scheduling

For comparable, known per-gate items let `c = verified/known applicable`. Show actual coverage `100c %` and optionally illustrative modeled effort completed:

```text
E(c) = 0.25*c            if c <= 0.8
E(c) = 0.2 + 4*(c-0.8)  if c > 0.8
```

The assumption is 80% of comparable cases can cost ~20% of total effort and the final 20% can cost ~80%. It is not measured time, ETA, an extra gate or a reason to reorder Prio. With unknown denominators mark estimates provisional or omit them. Do not aggregate incompatible gate-specific Pareto values into the official PASS count. The optional fractional coverage index sums only comparable observed test fractions, not Pareto estimates; **N/1332 remains based solely on real full gate PASSes**.

## Ownership and anti-bloat contract

- **Work1 #7:** genuine source-native↔2D causality and full P7 reference parity.
- **Work2 #19/#15:** one source-legal candidate generator, real paid evaluator, independent search/replay.
- **Prio #131:** shared native interface/capability blockers only; no retired P1/P2 gate work.
- **Merge:** sole M1 Actions launcher; production gate code computes PASS/FAIL/PARTIAL and the Action publishes the sole TSV and scoreboard on main. No manual scoring or repetitive heavy runs.
- **Clean:** remove superseded tools, redundant wrappers/docs/one-shot workflows after verifying replacements; keep the ideal repo map in [REPOSITORY_STRUCTURE](../REPOSITORY_STRUCTURE.md).

Agent handoff: read current main, this strategy, one priority/ownership file and your issue. Each work round should change real production behavior or expose one executable blocker. No extra checklist reports, JSON proof packages, progress ticks, copied plans or second simulator.
