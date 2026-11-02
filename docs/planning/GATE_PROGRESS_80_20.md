# FOREVER SIM — one production path to M1 (148/148)

**Mutable execution strategy / Prio-owned.** Normative product: [OVERALL_PLAN v5](../../OVERALL_PLAN.md) (do not rewrite). Normative acceptance: [PROCESS](../../PROCESS.md) and [P1–P7.5 predicates](../gates/README.md) (do not loosen). Current agent assignments: [WORK_PRIORITY](WORK_PRIORITY.md). Implementation failures, links, decisions: [issue #131](https://github.com/dosibjrn/forever-sim/issues/131) and the existing owner issues. **No other strategy, progress plan, evidence tree or gate-only simulator.**

## The one implementation we are building

```text
canonical Forever source + class/level/profile + objective
   -> legal gear, talent, ability and policy candidates
   -> ONE shared whole-build optimizer
   -> ONE paid production evaluator
        -> selected genuine pinned MythicSim Rust/Go combat
        -> real continuous gsim 2D world / movement / recovery where required
   -> real measured performance and behavior
   -> thin on-demand assertions for P1–P6 and P7.1–P7.5
```

**148 are input checkpoints, not 148 implementations.** P1/P2 check source legality and actually observed native/selected-engine effects; P3 calls the production gear scorer; P4/P5 call the same legal optimizer with independent cold 30/300-second budgets and genuine 100-mob results; P6 independently replays those winners; P7.1–P7.5 call the real native+2D evaluator on the separate exact pinned MythicSim reference, including independent searches and the required stochastic holdout. Same source/legal/combat implementation, different legitimate scenarios. Never substitute gsim-only, raw native-only, a source inventory, CI green or a wrapper for a hybrid acceptance requirement. Keep ALL existing numeric and source/engine criteria.

**Critical-path sequence (do not serially block other agents):**

1. **First contact:** for one likely-nearest checkpoint (currently Druid L60 Balance), attempt all eleven existing production-facing gate entry points, checking prerequisites cheaply before heavy work. Record the *first actual missing production operation* for each. A missing CLI provider is not proof that its scorer, optimizer or world runtime is missing. This discovery is deliberately short, not a milestone or documentation project.
2. **Fix the longest true dependency:** Work1 continues native↔real 2D causal execution/P7.1.3 [#7](https://github.com/dosibjrn/forever-sim/issues/7). Work2 continues one paid 100-mob source-legal optimizer/replay [#19](https://github.com/dosibjrn/forever-sim/issues/19), [#15](https://github.com/dosibjrn/forever-sim/issues/15). Prio independently fixes actual P1 native effects [#11](https://github.com/dosibjrn/forever-sim/issues/11) and P2 ranks [#12](https://github.com/dosibjrn/forever-sim/issues/12), and wires **thin calls** to production only where the real function already exists. Do not reset ongoing owner branches or build nine independent gate engines.
3. **First vertical 11/11:** run the heavy accepted gate once when genuinely runnable; correct actual RED→GREEN defects and retain the successful PASS timestamp. A checkpoint is certified ONLY when all eleven are mutually compatible under PROCESS. Get 0/148 → 1/148 without relaxing anything.
4. **Demonstrate genericity:** execute the same code and gate functions for a materially different class AND level (e.g. a pet class at L20 versus Druid L60) and fix generic effect/source failures rather than adding class-specific winners.
5. **Scale to 148:** populate the canonical source/legality and 148 input configurations, run on-demand PASSes across them, and focus on missing production behavior, not new adapters. Revalidate an old PASS only on material invalidation.

**Reason this minimizes total time:** the native/world engine and paid optimizer are shared prerequisites to many gates and classes, so parallel work on them has compounding returns; one early horizontal diagnosis prevents polishing P1/P2 in isolation while P7 cannot execute. After diagnosis, work returns to the highest-impact independent RED→GREEN fix. No repeated surveys, parallel engines or recurring heavy acceptance CI.

## Automatic M1 measurement (one tiny mechanism)

M1 has **148 × 11 = 1,628** approved checkpoint-gate pairs. Show BOTH exact counts, with no invented equivalence:

- **M1 passed gate executions:** `N/1628`, `100*N/1628 %`; **a row is added ONLY by the actual live gate runner returning PASS**. A missing/blocked/failed/diagnostic gate contributes zero.
- **Fully certified checkpoints:** `C/148`, only when the eleven gate PASSes for the same checkpoint are **mutually compatible** under the approved PROCESS. Eleven rows with absent/inconsistent compatibility provenance are a candidate, NOT a certified checkpoint.
- **Inside a failing gate:** measured applicable effects/ranks/slots over known applicable cases, if a defensible denominator exists, with unresolved source cases separate. For heterogeneous P4–P7 steps list concrete executable/missing functions rather than invent a percentage.

The minimal implementation is **existing** `tools/wf_gate.py` plus **one** `tools/m1_progress.py` display/invalidator and **one flat** `docs/planning/M1_PASSES.tsv` (no 1,628 JSON or Markdown files). After an actual source-backed, on-demand acceptance run:

```sh
python tools/wf_gate.py --class druid --level 60 --spec balance --gate P2 --record-pass
python tools/m1_progress.py
```

`--record-pass` records a UTC timestamp + HEAD revision and optional Actions URL/production compatibility ID **only on a real PASS**; no stored report can cause a PASS. **Only Merge** records a real accepted gate PASS, invalidates a materially stale PASS, and merges the updated single TSV to `main`; all other agents leave the ledger unchanged and supply direct run/commit/source/engine evidence in their existing issue/PR. Merge commits the stamp after verification, not as a reward for a green wrapper. This is the sole publication path for M1's official counts. Displaying progress does **not** rerun any gate. If a behavior/source/engine change invalidates a past pass, invalidate **only that pair** with `python tools/m1_progress.py --invalidate CLASS LEVEL SPEC GATE`, then rerun the real gate when fixed. A new commit *alone* does not invalidate unrelated passes. Keep ordinary focused unit regressions fast; 30/300s, 100-mob and 1,000+ fight tests are intentionally on-demand.

**Compatibility is fail-closed.** A passing live provider must supply trustworthy common source/ruleset/executor compatibility identity before eleven independent stamps may yield automatic 1/148. At present providers do not all emit one; the score command correctly separates `11/11 candidate` from `certified` until the actual integrated production path reports compatibility. Do not invent this field merely to move the number. The stamp is an audit record of executed code, not a substitute for execution.

### 80/20 means effort interpretation, never scheduling

For comparable, known per-gate items let `c = verified/known applicable`. Show **actual coverage** `100c %` and optionally **illustrative modeled effort completed**:

```text
E(c) = 0.25*c            if c <= 0.8
E(c) = 0.2 + 4*(c-0.8)  if c > 0.8
```

The assumption is 80% of comparable cases can cost ~20% of total effort and the final 20% can cost ~80%. Thus 83/103 = 80.6% measured rank coverage, but only ~22.3% *modeled* effort done. It is NOT measured time, ETA, an extra gate, or a reason to reorder Prio. With unknown denominators mark estimates *provisional* or omit them. Do not aggregate incompatible gate-specific Pareto values into M1; M1's **N/1628 is based only on actual full gate PASSes**.

## Ownership and anti-bloat contract

- **Work1 #7:** genuine source-native↔2D causality and full P7 reference parity.
- **Work2 #19/#15:** ONE source-legal candidate generator, real paid evaluator, independent search/replay.
- **Prio #131 + #11/#12:** brief full-gate first contact, then true unowned native ability/talent and thin acceptance repairs.
- **Merge:** **sole M1 progress/TSV publisher**: verify true gate PASS and source/backend compatibility, stamp on acceptance, merge safe code, publish exact N/1628 and C/148, no repetitive heavy runs.
- **Clean:** remove superseded tools, redundant wrappers/docs/one-shot workflows AFTER verifying replacements; keep the ideal repo map in [REPOSITORY_STRUCTURE](../REPOSITORY_STRUCTURE.md).

Agent handoff: **read the current main, one strategy here, one priority/ownership file, and your issue.** Each work round should change real production behavior or expose one executable blocker. No extra checklist reports, JSON proof packages, progress ticks, copied plans or second simulator. The next valid increment is an actual gate PASS or a measurable real mechanism fixed on the path to one.
