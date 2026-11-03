# FOREVER SIM — active work priority

**Purpose:** shortest path to 148/148 genuinely certified checkpoints under the active nine-gate set (P3–P6 and P7.1–P7.5). **Priority #1 is to DELETE retired P1/P2 and unneeded GameIR/Python-rules code, not port obsolete functionality to Rust.** Only functions genuinely required by active P3–P7.5 production gates or the optimizer may justify a small native-backed replacement. The owner decisions [#357](https://github.com/dosibjrn/forever-sim/issues/357) and [#359](https://github.com/dosibjrn/forever-sim/issues/359) override superseded implementation recipes in older issues.

This is a current execution queue, not a changelog or second gate/evidence system. History stays in Git; formal acceptance stays in [PROCESS](../../PROCESS.md), [gate contracts](../gates/README.md) and the Merge-owned [M1_PASSES.tsv](M1_PASSES.tsv). Agent responsibilities: [AUTONOMOUS_AGENTS](AUTONOMOUS_AGENTS.md); ideal end state: [REPOSITORY_STRUCTURE](../REPOSITORY_STRUCTURE.md).

## Active queue — execute in this order

### #1 P0 — retire P1/P2 and GameIR, without replacement scaffolding (#357 / #359)

**Owner clarification 2026-11-04:** the intention was to **remove P1, P2 and GameIR**, not to reproduce their retired behaviors behind new candidate interfaces, extra proof checks, 100-target diagnostics or transport abstractions. The game-mechanics authority remains MythicSim Rust, but an obsolete Python caller does **not** require migration when its only consumer is a retired gate, historical test, bounded demo or diagnostic. Delete that whole dead dependency chain instead.

**Clean's first implementation task:** delete retired `tools/wf_gate_p2_live.py` and its exclusive tests/workflows/fixtures after locating actual active P3–P7.5 imports; disentangle any surviving genuinely active regression rather than retaining the P2 gate as a helper. Then remove dead GameIR builders, bounded source-route diagnostics, evidence readers and Python game-rule modules, bottom-up from real *active* call sites. Delete associated dead tests and CI; Git history is sufficient. Do not first recreate these old features in Rust. PR #714 already owns part of the obsolete P2 native-diagnostic deletion: finish/merge that work rather than duplicate it.

**Work1:** do **not** rebuild deleted bounded GameIR level-route/evidence consumers via a new native route-candidate scoring boundary or test harness. PRs [#715](https://github.com/dosibjrn/forever-sim/pull/715) and [#716](https://github.com/dosibjrn/forever-sim/pull/716) explicitly report `M1 affected gates: none` and do not replace the legacy route; **hold them; do not integrate or expand them absent a demonstrated active-gate need**. Work1 may advance its real active gate repair [#718](https://github.com/dosibjrn/forever-sim/pull/718) / Druid L60 Balance P7.5 while Clean deletes the dead stack. Its last reported 300s/1000-stochastic result was **616.177645 DPS** below the **677.220060** floor ([run 41724127280](https://github.com/dosibjrn/forever-sim/actions/runs/41724127280)); candidate reachability work is useful only to the extent that it fixes a live optimizer/gate failure. Do not claim a PASS before the production run.

**Non-regression boundary:** P3–P7.5 and already accepted PASS receipts stay intact. When an *active* gate or actual optimizer still needs behavior currently implemented in GameIR, move **that exact behavior** to the already-selected MythicSim interface or simplify the caller using existing functionality; exercise that active call path, then delete its duplicate Python rules. Do **not** preserve unused route products, expired P1/P2 witnesses, stand-alone validations, imaginary acceptance constraints or Python fallback just to keep old tests green.

**Outcome:** no P1/P2 acceptance/proof subsystem, no live GameIR/Python Warcraft rules, no redundant replacement adapters. Progress is measured in removed unused code and real P3–P7.5 behavior, **not** PR count or interface/test count.

### #2 P0 — Work2 #15: joint optimizer, using MythicSim-owned legality

Continue [#15](https://github.com/dosibjrn/forever-sim/issues/15) as the independent #2 lane, but treat its historical “full source-backed legality adapters” wording as superseded by #359. The optimizer proposes gear/talents/APL candidates; **MythicSim validates/prepares/simulates them** and returns concrete valid/invalid/unsupported outcomes. Treat native talent refusals as authoritative results. Investigate and request a Rust-fork change only if a **required API/capability is demonstrably missing**, not to revalidate Rust talent rules; remove Python-side duplicated constraints instead of implementing new validators. Keep the shared generic search kernel and small paid regressions. The 28-profile 5s matrix remains diagnostic and 0/28 is not a certified result. Do not repeat unchanged 30s/300s sweeps or holdouts. Work2's HPS candidate-reachability PR [#699](https://github.com/dosibjrn/forever-sim/pull/699) is merged; current in-flight [#708](https://github.com/dosibjrn/forever-sim/pull/708) refreshes invalid L60 native talent baselines. Preserve #708 and do not duplicate it.

[#19](https://github.com/dosibjrn/forever-sim/issues/19) and draft [#537](https://github.com/dosibjrn/forever-sim/pull/537) remain HOLD pending a published/pinned suitable Rust implementation, damaged-actor paid HP-recovery proof and genuine 100-target trace. Do not claim that the merged source port alone establishes this.

### #3 P0 — finish the first genuine native↔world P7 checkpoint

Work1 retains [#7](https://github.com/dosibjrn/forever-sim/issues/7), the real two-way MythicSim Rust ↔ 2D world/action/ACK causality task. [#624](https://github.com/dosibjrn/forever-sim/pull/624) is merged and supplies native P7.5 paid gear/APL search composition; it is not itself a P7.5 PASS. The first Druid L60 Balance vertical has P7.1–P7.4 accepted and P7.5 still partial; finish the accepted-compatible-prior and final DPS-floor requirements only with the proper independent evidence. Continue actual world-state perturbation → native next-decision causality, then the full 300s search and independently frozen 1,000-iteration stochastic final where approved. The selected typed Balanced RNG pin remains `deb366e986dbc156e2242ddac3ac8c4ac854c107`; no World/2D diagnostic alone is a P7 PASS. Do not rerun unchanged heavy holdout just to fill the ledger.

### Parallel roles

- **Prio:** [#131](https://github.com/dosibjrn/forever-sim/issues/131) for the active 9-gate vertical and first free production repair. P1/P2 issues [#11](https://github.com/dosibjrn/forever-sim/issues/11) and [#12](https://github.com/dosibjrn/forever-sim/issues/12) are retired.
- **Merge:** integrate tested bounded PRs and alone launch official affected-gate runs/write eligible M1 evidence. A structural migration is mergeable before the whole checkpoint passes if supported behavior is preserved.
- **All agents:** read newest main and unresolved owned PR feedback first; preserve already accepted gate evidence. Prefer **delete retired/dead functionality → preserve active gate behavior → use the existing native engine only where needed**. No interface-first migration of obsolete callers.

## Next-decision rule

At every Prio cycle, recompute from latest main, real active-gate callers and measured M1. Prioritize deletion of retired P1/P2/GameIR paths and genuine active-gate production fixes; never choose new adapter work because a dead GameIR demo happens to import it. Preserve in-flight PRs for a safe Merge handoff; do not create duplicate owner branches. Only if an actual active gate demonstrates a missing required native capability, record its exact failure in #359 and fix it; otherwise delete the obsolete caller rather than extending Rust. Only promote #2/#3 above #1 on a demonstrated blocker or explicit owner reprioritization.

**Hygiene:** replace superseded status, stale PR heads and obsolete instructions in place; keep history in Git/issues, not this file. No new acceptance gates and no manual M1 ledger changes.
