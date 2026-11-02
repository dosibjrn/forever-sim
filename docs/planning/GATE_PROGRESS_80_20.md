# P1–P7.5 — 80/20 progress and critical-path plan for Prio

**Status:** Mutable execution plan for the Prio agent, **not** a change to approved
[PROCESS](../../PROCESS.md), [gate predicates](../gates/README.md) or
[OVERALL PLAN](../../OVERALL_PLAN.md). The target is **148/148 genuinely
accepted checkpoints**, starting with 0→1, then one reusable production path
for the other 147. One source/legal gear × talents × APL/pull/recovery search,
one actual native combat executor and one gsim 2D world: do not reimplement
those systems inside gate tests.

## First delivery: one real first pass through every gate

**Implement → run against production → identify the first real defect → fix → repeat only what changed.**
Before polishing one gate to perfection, Prio must establish a **first attempted
production acceptance pass for all eleven existing gates** (P1–P6 and P7.1–P7.5)
on the *same chosen checkpoint*. This is a **thin horizontal discovery pass**,
followed by the smallest dependency-ordered fixes and the full vertical checkpoint.
It does **not** mean all eleven must PASS initially or that independently owned
Work1/Work2 development must stop.

Use the existing `tools/wf_gate.py --class ... --level ... --spec ... --gate Pn`
or the exact real production call that gate already uses. Each gate's first
attempt must expose an **actual behavior/result or the first concrete missing
production dependency**. If the engine/optimizer/reference needed to execute a
heavy gate does not yet exist, fail fast with the specific missing function or
runtime capability; **do not spend a 300-second budget on known-unrunnable work**,
and do not count a schema test or a generated BLOCKED report as an executed gate.
Once prerequisites are ready, perform the real approved test once.

| First pass | Existing production code that must eventually run |
| --- | --- |
| **P1 / P2** | Source-legal spells / talent allocations → actual selected MythicSim/production effects and search admission |
| **P3** | Real legal item DB → existing build-context gear scorer and stat-weight mechanics |
| **P4 / P5 / P6** | Same real production whole-build evaluator → paid 100-mob leveling, independent 30s/300s searches, comparable finalist replays |
| **P7.1** | Exact saved reference → real native engine → real live 2D/native causality |
| **P7.2 / P7.3 / P7.4 / P7.5** | Same real live 2D/native evaluator → cold APL/talent/gear/joint search and required frozen holdout |

**Code-first definition of progress:** a change counts as useful engineering work
when it enables/fixes a real production operation, removes a measured failure,
makes a genuine gate executable, or earns a genuine gate PASS. Merely adding a
per-gate wrapper, unit-test scaffold, synthetic fixture, CI matrix, JSON,
checklist, status page or documentation does **not** advance implementation.
Do not build separate gate-only combat logic, search algorithms, scores or
a continuously executing acceptance suite. Gate validation is a **thin
on-demand call into the real implementation**, plus assertions of the existing
approved predicate. Normal *focused* unit/regression tests can protect changed
production code; **do not create always-run P1–P7 acceptance unit tests**.

**First pass reporting:** keep the moving discussion and exact failed
production calls in its GitHub issue, not another evidence/document tree.
For each gate, give only: `callable/executed?`, **observed behavior or first
concrete defect**, and next code change / owning issue. For homogeneous gates,
show the existing code-derived `verified/relevant` fraction and any provisional
scope; for heterogeneous gates show the missing real steps, **not an invented
percentage**. Prio updates this *one living plan* only when execution strategy,
cross-gate dependencies or ownership genuinely changes. Issue comments carry
the conversation.

**Acceptance cadence:** after an actual full successful on-demand run, retain
PASS and timestamp. Do not rerun a passed expensive gate on every hourly task,
PR, commit or CI cycle—only when a materially relevant behavior/source/scenario
change invalidates it. Do not reinterpret a successful native-only subtest as
a live-2D gate when 2D causality is part of that gate.

## Generic implementation path: gates validate one real product

**P1–P7.5 are on-demand integration/acceptance tests, NOT 5 ms unit tests.**
A real 30/300-second search, 100-mob run or ≥1000-fight stochastic holdout
is a legitimate gate execution. Run once for PASS and retain timestamp;
repeat only if a relevant production change invalidates it. Keep small,
focused unit tests for regressions, not as replacement P1–P7 suites or
permanent expensive CI.

**One generic production path for all 148 checkpoints:**

```text
canonical class/level/spec source + legal abilities/talents/gear
    -> ONE legal candidate generator / whole-build optimizer
    -> ONE production evaluator
       -> selected genuine MythicSim Rust/Go combat
       -> real persistent gsim 2D world/recovery when applicable
    -> observed effects, scores and searches
    -> thin on-demand P1–P7.5 assertions against those same functions
```

The leveling 100-mob scenario and P7 saved DPS reference differ in
configuration, **not** in the core combat/legality engine. Each gate
selects its actual scenario, invokes existing production functions and
checks the approved behavioral predicate. P1 native effects need no
parallel Python GameIR action implementation.

**Code-first order:**

1. **First-pass all gates** on one selected checkpoint: invoke an existing
   real function, or name the *first actual missing production dependency*.
   Do not build mock gate scaffolding to get a GREEN or run 300 seconds
   when the engine is known not to work.
2. **Implement the missing shared production capability** in place:
   source-legal action/talent effects → native combat → actual world feedback
   → persistent paid 100-mob evaluation → same legal whole-build search →
   exact saved-reference evaluation and independent searches. Test the
   smallest real failed behavior and keep existing Work1/Work2 ownership.
   **Never duplicate combat, search or scorer logic inside gate tooling.**
3. **Validate first checkpoint vertically**, retaining independently earned
   PASS+timestamp for each compatible gate. Then run the **same code**
   at a different class and level (e.g. Hunter with pet/autoattack versus
   Druid caster; L20 versus L60). Fix common effect families or source
   rules rather than adding per-class runners, hardcoded whitelists or
   148 separate implementations.
4. **Coverage means product readiness**, not paperwork: all accepted
   checkpoints must actually exercise legal spells/talents, gear scoring,
   continuous combat/recovery, independent timed search and selected
   native↔world reference comparisons. The 148 class/level/profile cases
   then demonstrate broad functioning across the approved scope; they
   do not claim every level 1–60 or every untested mechanic is perfect.

**No MD/JSON busywork:** this is the **one updated plan**;
[issue #131](https://github.com/dosibjrn/forever-sim/issues/131)
holds decisions, failures and discussion; production PRs hold code.
No new evidence-document tree, per-spell result JSON, permanent
status matrix, duplicate gate-only simulator/optimizer, recurring heavy
test suite or additional checkpoint. Diagnostic numerator/denominator
comes directly from actual production executions; a real gate PASS needs
only its existing PASS+timestamp.

## What 80/20 means — *effort estimate*, NOT work ordering

Pareto is a **hypothesis for estimating the effort still ahead**, not a reason to change issue order or to postpone the difficult tail. Keep Prio's critical-path ordering and Work1/Work2 ownership exactly as they are. When measured unit coverage is known, report **both**:
1. **Behavioral coverage** `c = real passed / currently known applicable` (directly measured).
2. **Illustrative Pareto effort completed** `E(c)` (model-derived estimate, **not measured hours or acceptance**).

Use the minimal two-segment mapping: assume the first 80% of comparable cases cost 20% of total effort and the final 20% cost 80%. For a fraction `c` in `[0, 1]`:

```text
E(c) = 0.25 * c                  when 0 <= c <= 0.8
E(c) = 0.20 + 4 * (c - 0.8)     when 0.8 < c <= 1
```

Examples: coverage 50% → estimated work 12.5%; coverage 80% → work 20%; coverage 90% → work 60%; coverage 95% → work 80%; coverage 100% → work 100%. Previous P2 74/103 = 71.8% coverage → ~18.0% modeled work; 83/103 = 80.6% coverage → ~22.3% modeled work. **The increase in E is only modeled movement; it is not proof that exactly that fraction of engineer-hours was spent.** This model makes the apparent movement near the end of a long gate more meaningful, while showing why 80% test coverage need not mean near-completion.

Use this only when the unit count has a defensible, roughly comparable denominator. If source legality/universe is unfinished, mark **both percentages provisional** and disclose unknown cases; newly found cases may reduce them. If no meaningful denominator exists, or the gate consists of a few heterogeneous steps (e.g. P7.1.1/.2/.3, P4/P5 infrastructure), show the concrete completed/missing behaviors **without** applying a spurious effort percentage. Never weight a checkpoint's total progress by adding incompatible per-gate effort estimates.

The original [draft PR #60](https://github.com/dosibjrn/forever-sim/pull/60) reports observed/checked effects and diagnostic threshold ticks at 50/80/85/88/91/93/95/97/99% **coverage**. Those remain diagnostic source/runtime counters, not the Pareto work estimate, not new gates and not a reason to re-order implementation. Reporting the continuous `E(c)` is preferable to celebrating threshold ticks. **Only a real accepted gate earns PASS**, irrespective of the model.

A real blocking implementation fix may advance the critical path without changing either percentage; report that concrete fix, not an invented progress tick. Do not work on easy cases merely to maximize E or split cases to manipulate it. Keep existing 80/20 acceptance thresholds entirely unchanged (there are none); this is optional communication and estimation.

## Minimal measurement, by approved gate

| Gate | Reusable actual-execution subunits | What the final approved PASS still requires |
| --- | --- | --- |
| **P1** | Source-verified legal and relevant ability/rank → selected native Rust/Go actually executes a suitable ability effect (positive/negative control or targeted assertion); count per *genuine* effect. Class/level/spec/talent eligibility resolves the source denominator. Report autoattack, pet, passive and conditional channels distinctly; explicit `NOT_RELEVANT_TO_SIMULATION` list is neither failure nor PASS. | Every required relevant ability behaves and is available to the actual optimizer. **No Python GameIR replica requirement** for native abilities. For world-dependent effects use real gsim 2D. No mere cast counter, APL-removal DPS proxy or gsim-only result counted as **native** effect coverage. |
| **P2** | Legal reachable talent ranks; each verified through source-derived allocation, actual selected-engine mechanic, negative/adjacent-rank test and candidate use where required. Prefer generic effect families. | All reachable ranks meet [P1–P2](../gates/P1-P2.md); no invented semantic-verification gate. |
| **P3** | Real legal top-5-by-ilvl per equipment slot, score finite and genuinely affected by applicable stats and weight channels; record samples covered and unresolved relevant channels. | Whole [P3 gear/weight predicate](../gates/P3.md), not only sampling or metadata completeness. |
| **P4** | Source-legal whole-build proposal → selected integrated production evaluation → persistent paid recovery → 100-mob result → genuinely independent 30s cold search. Count meaningful executable search components and candidates; do not turn test progress into the acceptance result. | All P4 legality, search budget, 100 consecutive mobs and output criteria. |
| **P5** | Reuse P4 production evaluator, 300s independent cold search, actual unique paid candidates and final 100-mob replay. | Actual 300s and **N300 ≥ 10 × N30** plus all other P5 predicates. |
| **P6** | Reuse P4/P5 winners; 100-mob paired replays with identical actor/source/target/resource/recovery and actual times. | **T30 ≤ 1.01 × T300** on comparable actual seconds/mob, not a proxy. |
| **P7.1** | Reproduce exact saved reference configuration (1.1), actual Rust/Go native reference (1.2), actual 2D↔native causal same-reference session (1.3). Each is an existing **P7.1 subtest**, not a new gate. | Native and hybrid DPS ≥ exact saved reference, with required controlled source/encounter parity. |
| **P7.2–P7.4** | Reuse the same genuine integrated paid evaluator; independent 300s APL, talent, gear searches respectively. Measure legal paid unique candidates and current strongest accepted-compatible measured DPS. | Each real cold 300s search, true selected-engine/2D execution and DPS ≥ **99%** of saved external reference. |
| **P7.5** | Reuse joint gear × talents × APL search; cold 300s paid candidates, then *independent frozen* stochastic holdout. | ≥1000 genuine stochastic fights and holdout **mean DPS ≥ max(external, 0.99 × strongest accepted compatible prior P7.1–P7.4 mean)**. Do not invent a confidence-bound acceptance test. |

When exact denominators are truly unknown, a measured per-unit diagnostic
percentage is useful, **but gate acceptance remains binary** and subject to
the real approved test. Keep stage readiness, component coverage and passed
gate **separately**.

## Immediate P1 gap: retire the misleading `gsim 21/21` → native-P1 ticks

- [Merged #95](https://github.com/dosibjrn/forever-sim/pull/95)
  already put native black-box source inventory and the PROCESS P1 boundary
  in main. The old [draft #60](https://github.com/dosibjrn/forever-sim/pull/60)
  counts 50/80/85/88/91/93/95/97/99 from **gsim** effect observations.
  That is a gsim diagnostic, not a source-verified **native P1** percentage.
- `tools/p1_native_progress.py` is the minimal shared **native-only diagnostic
  reducer**, with thresholds above. It counts **only actual selected native
  direct behavioral assertions**, and counts neither the existing gsim proxy
  nor `tools/wf_p1_native_effects.py`'s APL-row-removal metric change as
  a verified effect. Native APL reports now declare
  `apl_metric_delta_observed`, not `effect_observed`.
- The source inventory in main lists **provisional** raw level-eligible spell
  candidates, not verified learned/legally granted spells. These may be
  candidates for experiments but are **not** a final P1 denominator.
  Missing/unknown source acquisition remains explicit. Do not show
  `Hunter L20 = 2/61` or `89/89` as actual native ability coverage.
- **Next real PR after this:** for one source-legal Druid/Hunter ability,
  execute the real pinned MythicSim Rust/Go action, observe one meaningful
  spell-specific change in native combat state/events, include suitable
  negative control. Return a real runtime-produced, effect-verified outcome
  through the shared reducer; the nine diagnostic milestones then move from
  actual native behavior, not text/schema evidence. Reuse it across every
  class/level. Source legality and actual optimizer admission must also be
  independently confirmed before final P1.
- Do **not** build a second combat engine, an alternative optimizer, a
  stand-alone fake P1 simulator or a new mandatory event export API merely
  for a test. Use available real native execution results; extend the
  selected native test boundary **only if needed** to observe the effects
  actually required by P1.

## Portfolio / agent action

**Prio** reads [WORK_PRIORITY](WORK_PRIORITY.md) and open issues/PRs at
each run and maintains the **minimum-total-time critical path**:

1. Preserve **Work1 = #7** genuine world ↔ native causality / saved P7
   encounter; **Work2 = #19/#15** same production paid evaluator/search.
   Do not steal or reset these ongoing branches without a real dependency change.
2. Prio owns independently actionable **#11 P1 native direct behavior**
   and **#12 P2 rank behavior**. Fix the first exact failing native/source
   case. Run a focused real behavior test. Report verified numerator/denominator,
   unknown source cases and next concrete failure, not merely labels.
3. **First pass all eleven gates for one checkpoint, then finish vertically:**
   call real production functions where runnable and record the exact first
   failure for the rest in the coordinating issue. Reuse Work1/Work2's
   production path to remove those failures. Earn each genuine accepted gate
   once and keep its PASS timestamp; do not postpone first-contact discovery
   of later gates until P1/P2 are perfectly polished.
4. **After 1/148**, expand the common executor/search/tests across levels
   and specs. Favor changes removing many class-level failures before
   special-case tail fixes. Batch sourced effect families where appropriate;
   do not fake missing legal spells as non-relevant.
5. **Merge** reviews fast tests and exact-HEAD regressions, integrates
   safely without demanding expensive acceptance reruns for unrelated edits.
   **Clean** removes obsolete duplicate code as successor paths become real;
   architecture, not cosmetic file count, is its primary criterion.

**Do not edit the sacred PROCESS/OVERALL PLAN** to impose this optional Pareto estimate or diagnostic ticks as acceptance requirements. If any desired predicate/threshold
actually changes, request explicit owner approval first.
