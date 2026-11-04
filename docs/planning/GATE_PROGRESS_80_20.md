# FOREVER SIM — one production path to M1 (148/148)

**Mutable execution strategy / Prio-owned.** Normative product: [OVERALL_PLAN v6](../../OVERALL_PLAN.md) (do not rewrite). Normative acceptance: [PROCESS](../../PROCESS.md) and [active P3–P7.5 predicates](../gates/README.md) (do not loosen). Current agent assignments: [WORK_PRIORITY](WORK_PRIORITY.md). Implementation failures, links, decisions: [issue #131](https://github.com/dosibjrn/forever-sim/issues/131) and the existing owner issues. **No other strategy, progress plan, evidence tree or gate-only simulator.**

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

**148 are input checkpoints, not 148 implementations.** MythicSim native prepare/execute owns ability/talent availability, legality and effects; no separate P1/P2 acceptance gate remains. P3 calls the production gear scorer; P4/P5 call the same legal optimizer with independent cold 30/300-second budgets and genuine 100-mob results; P6 independently replays those winners; P7.1–P7.5 call the real native+2D evaluator on the separate exact pinned MythicSim reference, including independent **low-repeat deterministic balanced-RNG** searches and only the **final frozen 1,000-stochastic-fight reference/holdout**. P7.1–P7.4 final floor is **0.99 × saved reference DPS**; P7.5 final floor is **0.93 × max(saved reference DPS, strongest accepted-compatible prior)**. The saved request's historical iterations are not an acceptance quota. Same source/legal/combat implementation, different legitimate scenarios. Never substitute gsim-only, raw native-only, a source inventory, CI green or a wrapper for a hybrid acceptance requirement. Keep ALL existing numeric and source/engine criteria.

**Critical-path sequence (do not serially block other agents):**

1. **First contact:** for one likely-nearest checkpoint (currently Druid L60 Balance), attempt all nine active production-facing gate entry points, checking prerequisites cheaply before heavy work. Record the *first actual missing production operation* for each. A missing CLI provider is not proof that its scorer, optimizer or world runtime is missing. This discovery is deliberately short, not a milestone or documentation project.
2. **Fix the longest true dependency:** Work1 continues native↔real 2D causal execution/P7.1.3 [#7](https://github.com/dosibjrn/forever-sim/issues/7). Work2 continues one paid 100-mob source-legal optimizer/replay [#19](https://github.com/dosibjrn/forever-sim/issues/19), [#15](https://github.com/dosibjrn/forever-sim/issues/15). Prio owns the first active-gate vertical and takes the first free executable production slice after respecting Work1/Work2 ownership; the P1/P2 issues [#11](https://github.com/dosibjrn/forever-sim/issues/11) and [#12](https://github.com/dosibjrn/forever-sim/issues/12) are retired. Do not reset ongoing owner branches or build nine independent gate engines.
3. **First vertical 9/9:** run the heavy accepted gate once when genuinely runnable; correct actual RED→GREEN defects and retain the successful PASS timestamp. A checkpoint is certified when all nine real active gates PASS. No extra certificate is required.
4. **Demonstrate genericity:** execute the same code and gate functions for a materially different class AND level (e.g. a pet class at L20 versus Druid L60) and fix generic effect/source failures rather than adding class-specific winners.
5. **Scale to 148:** populate the canonical source/legality and 148 input configurations, run on-demand PASSes across them, and focus on missing production behavior, not new adapters. Revalidate an old PASS only on material invalidation.

**Reason this minimizes total time:** the native/world engine and paid optimizer are shared prerequisites to many gates and classes, so parallel work on them has compounding returns; one early horizontal diagnosis prevents polishing one gate in isolation while P7 cannot execute. After diagnosis, work returns to the highest-impact independent RED→GREEN fix. No repeated surveys, parallel engines or recurring heavy acceptance CI.

## Automatic M1 measurement (one tiny mechanism)

M1 has **148 × 9 = 1,332** active checkpoint-gate pairs. Show BOTH exact counts, with no invented equivalence:

- **M1 passed gate executions:** `N/1332`, `100*N/1332 %`; **a row is added ONLY by the actual live gate runner returning PASS**. A missing/blocked/failed gate contributes zero to the strict accepted PASS count; a genuinely executed FAIL or P7 objective BLOCKED run may still earn a separately labeled noncertifying PARTIAL.
- **Fully accepted checkpoints:** `C/148` counts checkpoints with nine genuine active gate PASSes. Source/runtime/scenario correctness belongs to the gates themselves, never a separate cross-gate metadata certificate.
- **Inside a failing gate:** actual executed `verified/applicable` effects/ranks/slots, **percentage and optional Pareto work model**. A full PASS is 1; a partially tested gate with real 83/103 coverage is **0.806 measured gate-equivalents**, *not 0.806 PASS gates*. For P7, use the actual selected native↔2D DPS / required DPS target instead of fake simulation-count denominators. For heterogeneous stages without a defensible denominator show concrete missing functions, no invented percentage. Unknown source scope is marked provisional.
- **Optional continuous M1 progress index:** `(full PASS gates + sum(actual partial gate coverage fractions)) / 1332 × 100%`. This is a **descriptive diagnostic estimate**, not the certified `N/1332` acceptance percentage, never substituted for the official PASS numerator or checkpoint count. For example, if nothing else has passed and one active gate is verified at 83/103, the index is `(83/103)/1332 × 100 ≈ 0.0605%`, while **accepted active gates remain 0/1332**. Record partials only from actual on-demand production test execution, not source inventories or mock runners.

The minimal implementation is **existing** `tools/wf_gate.py` plus **one** `tools/m1_progress.py` display/invalidator and **the same flat** `docs/planning/M1_PASSES.tsv` with either accepted PASS stamps or genuine measured PARTIAL fractions (no 1,332 JSON or Markdown files). After an actual source-backed, on-demand acceptance run:

```sh
python tools/wf_gate.py --class druid --level 60 --spec balance --gate P3 --record-pass
python tools/m1_progress.py
```

**Automatic script-owned results:** Work1/Work2/Prio/Clean identify `M1 affected gates: class:level:spec:gate ...` in each implementation PR. Merge deduplicates the list and **only launches** the trusted GitHub Action with `/m1-run ...` on an already merged PR; it does not hand-grade PASS/FAIL or manually copy numbers. Actions runs the real `wf_gate.py --record-progress`, automatically records genuine gate PASS or eligible executed PARTIAL in the one TSV on `main` and runs `m1_progress.py` to display the scoreboard. A measured P7 coupled live DPS can be provisional PARTIAL even if a distinct UI/acceptance requirement leaves the gate BLOCKED. P4/P5 may measure sourced ability execution in completed paid runtime screens without pretending that one short probe is the 30/300s full gate. The first positive executed behavior needs no full-gate setup. No synthetic count from 1000 fight samples, provider existence, gear-slot visits or source-only inventory is allowed.

**Monotonic partial display:** one gate row holds its **best previously measured** comparable fraction; a lower subsequent outcome remains visible in Actions logs as a regression/scope-change warning, not a silent drop in the historical progress index. A changed denominator never gains credit merely by discarding previously verified behaviors. FULL PASS always supersedes partial; only a material invalidation removes an accepted PASS. A 100% measured *subcomponent* is still only PARTIAL if another gate predicate fails. This is an observed historical upper watermark, not a guarantee of present regression-free behavior. An approved semantic change may intentionally invalidate an obsolete row.

**No hidden checkpoint gate.** Nine genuinely accepted gate PASSes suffice. The historical optional `compatibility_id` TSV column is metadata, not a producer task or certification switch. If a real gate result is invalid, invalidate that gate rather than adding a checkpoint-level certificate.

### 80/20 means effort interpretation, never scheduling

For comparable, known per-gate items let `c = verified/known applicable`. Show **actual coverage** `100c %` and optionally **illustrative modeled effort completed**:

```text
E(c) = 0.25*c            if c <= 0.8
E(c) = 0.2 + 4*(c-0.8)  if c > 0.8
```

The assumption is 80% of comparable cases can cost ~20% of total effort and the final 20% can cost ~80%. Thus 83/103 = 80.6% measured rank coverage, but only ~22.3% *modeled* effort done. It is NOT measured time, ETA, an extra gate, or a reason to reorder Prio. With unknown denominators mark estimates *provisional* or omit them. Do not aggregate incompatible gate-specific Pareto values into the official PASS count. The optional **fractional coverage index** sums only comparable observed test fractions, *not* Pareto estimates; **N/1332 stays based solely on real full gate PASSes**.

## Ownership and anti-bloat contract

- **Work1 #7:** genuine source-native↔2D causality and full P7 reference parity.
- **Work2 #19/#15:** ONE source-legal candidate generator, real paid evaluator, independent search/replay.
- **Prio #131:** first active 9-gate vertical, then the first free executable active-gate production repair. P1/P2 issues #11/#12 are retired.
- **Merge:** sole M1 Actions launcher: merge safe code, batch affected gate arguments from PR descriptions; the production gate script computes PASS/FAIL/PARTIAL, the Action publishes the sole TSV and scoreboard in main. No manual scoring or repetitive heavy runs.
- **Clean:** remove superseded tools, redundant wrappers/docs/one-shot workflows AFTER verifying replacements; keep the ideal repo map in [REPOSITORY_STRUCTURE](../REPOSITORY_STRUCTURE.md).

Agent handoff: **read the current main, one strategy here, one priority/ownership file, and your issue.** Each work round should change real production behavior or expose one executable blocker. No extra checklist reports, JSON proof packages, progress ticks, copied plans or second simulator. The next valid increment is an actual gate PASS or a measurable real mechanism fixed on the path to one.
