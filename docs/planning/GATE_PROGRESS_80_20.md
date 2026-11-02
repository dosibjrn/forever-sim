# P1–P7.5 — 80/20 progress and critical-path plan for Prio

**Status:** Mutable execution plan for the Prio agent, **not** a change to approved
[PROCESS](../../PROCESS.md), [gate predicates](../gates/README.md) or
[OVERALL PLAN](../../OVERALL_PLAN.md). The target is **148/148 genuinely
accepted checkpoints**, starting with 0→1, then one reusable production path
for the other 147. One source/legal gear × talents × APL/pull/recovery search,
one actual native combat executor and one gsim 2D world: do not reimplement
those systems inside gate tests.

## What 80/20 means

Use the Pareto principle for **the order and granularity of work**, not to
lower an acceptance threshold. First solve reusable mechanisms that remove
most blockers across many classes/levels; only then address rare conditional
abilities, specialized triggers and the final tail. Split each gate into
**individually executable, meaningful behavioral slices** that an agent can
finish in one small PR/turn. If a slice is already verified by an existing
production function/test, reuse it: do not duplicate the implementation or
re-run a heavy acceptance suite.

Show **diagnostic progress milestones** at **50, 80, 85, 88, 91, 93, 95,
97 and 99 percent** of an actually counted population. The **10th and final
milestone is the approved gate's real PASS**, not a rounded-up 100% count.
A 99%-covered source/action list is not a passing gate. These milestones
are derived from the current real execution results, **not manually maintained
JSONs, invented permanent ledgers or a replacement for the 148 score**.
When exact total is unknown, say **estimated/provisional**, expose the
unknown part, and use a conservative lower-bound denominator or an unscaled
list of resolved cases. Do not shrink the denominator by omitting missing
source records. A milestone can regress when the true scope increases;
do not freeze a misleading percentage.

A real blocking implementation change may advance the critical path before
any threshold is crossed: report the **specific executable failure removed**
rather than inventing a tick. Agents should prefer a testable slice they can
actually complete, but never game the progress indicator by splitting
trivial files, writing documentation-only PASS receipts or counting fixture
registration as behavior.

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
3. **Single-checkpoint vertical completion** is the routing objective:
   reuse existing verified behavior, integrate Work1/Work2's production
   function, earn missing P1–P7.5 gates once, record at least PASS+timestamp
   and report **1/148** only when all compatible gates passed.
4. **After 1/148**, expand the common executor/search/tests across levels
   and specs. Favor changes removing many class-level failures before
   special-case tail fixes. Batch sourced effect families where appropriate;
   do not fake missing legal spells as non-relevant.
5. **Merge** reviews fast tests and exact-HEAD regressions, integrates
   safely without demanding expensive acceptance reruns for unrelated edits.
   **Clean** removes obsolete duplicate code as successor paths become real;
   architecture, not cosmetic file count, is its primary criterion.

**Do not edit the sacred PROCESS/OVERALL PLAN** to impose these diagnostic
progress ticks as a new requirement. If any desired predicate/threshold
actually changes, request explicit owner approval first.
