# WoW Forever — OVERALL PLAN v9 (OWNER-DIRECTED)

**Date:** 2026-11-08  
**Status:** **OWNER-DIRECTED amendment to v8.** v9 clarifies Rust-owned native leveling simulation and Forever-owned end-to-end decision orchestration. The approved v8 acceptance gates, 148-checkpoint finish line, v7 single-source game-fact ownership and v6 P1/P2 retirement are unchanged. Git history retains every earlier approval.
**Purpose:** Define WHAT is built, the end-state and precisely when DONE DONE occurs. No gate implementation procedure or changeable milestone ordering belongs here; those live in PROCESS and milestone plans.

## Owner direction v9 — native single-process leveling + Forever end-to-end decisions (2026-11-08)

**The desired execution boundary is one Rust/msim simulation per candidate, not per-event Python↔Rust cross-API handshakes.** For the selected source/level/scenario, pinned MythicSim Rust owns the *entire* continuously timed 2D leveling encounter: world and mob positions, distance, facing and movement, target selection, native legal combat/APL/pets/DoTs, live world mob HP and lethal events, continuous actor resources and cooldowns, and actual **paid recovery, eating and drinking between pulls**. Mob combat, movement and recovery share one native clock. The real objective is elapsed leveling time including combat, movement and recovery; survival is a requirement, **not** "HP/mana must last 100 mobs without rest." Recover when needed to continue safely, and optimize where/how long to eat or drink; simultaneous HP/mana replenishment is allowed only according to sourced native rules. Existing fixed 12s passive waiting is *not* food/drink. Avoid deriving kills, buffs, mana/HP transitions, or world movement in Python. Retain old external gsim bridge only as a parity oracle during migration, not the target production runtime.

**Forever Sim owns the *whole* end-to-end 1–60 level-range search and decisions** (not merely a local level-30 Warlock build). It selects/request sources and scenarios, legal alternatives from native Rust, optimizes talent allocation and progression, gear and acquisition, APL, pet, pull/recovery policy, respec/dual-spec constraints, level transitions, and playable continuous leveling routes; it requests whole-build Rust executions and consumes measured receipts. Python may do candidate proposal, search, surrogate/ranking, dynamic programming across level frontiers, comparison, and publication. It does **not** replicate Warcraft spells, combat, item/talent legality or food/drink effects. Source-specific class restrictions stay within the pinned native engine. Build transitions and respec costs are charged when applicable; no hypothetical free gear swap, training or level boundary resets.

**Preserve the original player-facing decision questions**, including the existing `src/v2/decision_pipeline.py`, `decision_result.py`, `dual_spec.py` and publications `endpoint_paths`, `spec_regret`, `dual_spec`, while replacing obsolete Python gameplay/legality implementations with native measured inputs. On requested level ranges (e.g. 10–30, 1–40, 1–60), answer:
- *Which spec/build and talent progression is fastest for solo leveling?* Compare each sourced spec constraint with the unrestricted shortest executable route.
- *What is the cost of committing my main leveling spec to healer or tank?* Report the route-time penalty relative to unrestricted, in seconds/hours and %, together with chosen gear/talents/APL and level-specific regret; distinguish a constrained healer/tank main from mere healing/tanking ability.
- *Dual spec becomes available at level 40: which **two** specs should I choose?* Optimize the actual pair and active-spec schedule across later levels, including any sourced purchase, swap, respec, gear acquisition, and healing/tanking obligations. Compare unrestricted best pair to a pair forced to include healer or tank and quantify **how much slower** the leveling route becomes; also compare main-role-healer/tank versus second-role-healer/tank constraints.
- Answer counterfactual "what if" role, talent, gear and level-range constraints using the same measured native cost data, with honest unverified-range labeling. Never substitute disconnected single-level winners for a valid continuous route.

The prior `dual_spec.py` restricts switches to level boundaries and assumes zero switch cost; those are **historical modeling assumptions**, not automatically source-verified Forever rules. Keep dual-spec unlock at **40** as the requested ruleset setting, and only charge sourced transition/switch/purchase costs; expose unknown costs rather than silently assuming all are free. Existing `state/decisions/forever` records and partially verified class-level frontiers are historical evidence and question/schema references, **not accepted 1–60 routes**.

**Execution/priority discipline:** Deliver the smallest real Warlock L30 8/100-mob native 2D-with-recovery vertical first, preserve source-native Shoot and other APL choices, then make the fast evaluator reusable for every class/level. Compare the same native build/scenario with the former external world bridge and report parity differences and measured wall time before declaring a speedup. Publish source-legal continuous full-chain results and later route decisions without inventing new P3–P7.5 gates or changing v8's 1,332 pair denominator. Active M1 gate handoffs continue under Prio's actual verified critical path; this direction guides shared architecture and product end-state rather than manufacturing a new acceptance veto.

## Owner-approved v8 acceptance simplification (2026-11-04)

Keep all **148 checkpoints, nine active P3–P7.5 gates (1,332 pairs), M1 partial-inclusive diagnostic and real native-paid results**. P3 now tests representative legal gear and mechanically relevant score sensitivity, not arbitrary positive weights. P4/P5 use genuine **30s and 300s snapshots of one cold 300s search**; P4–P6 retain distinct winners' real continuous **100-mob** leveling/recovery/survival results, but identical compatible receipts may be reused. P7's pinned, stationary non-attacking DPS reference is measured directly in the selected genuine MythicSim Rust/Go engine: P7.1 uses one reproducible stochastic baseline; P7.2–P7.4 use genuinely paid single-axis changed alternatives; P7.5 retains the **independent cold 300s joint search, 1,000 stochastic fights and 93% accepted-compatible comparison**. The P7-only 2D handshake, duplicate axis holdouts and duplicative 100-mob replays are no longer acceptance prerequisites. **P4–P6's real spatial native↔world causality is unchanged.** Exact predicates live only in [gate contracts](docs/gates/README.md). A new contract does not automatically grant a historical or unexecuted PASS.

## Owner-approved v7 single-source architecture amendment (2026-11-04)

**MythicSim Rust is the source of game facts and available optimization choices.** Its pinned, maintained fork owns items/equipment and enchants, spells and ranks, class talent trees/rank limits and eligibility, available APL actions/conditions, full-build legality and Warcraft mechanics. These data and relevant preparation/spellbook information already exist in Rust; reuse them rather than copy them into Forever. Their existence does **not** imply that an exhaustive legal-options enumeration API is already implemented or that all restrictions are verified: implement any *actually needed* missing option/capability or legality in the Rust fork, test it there and promote a tested exact SHA.

**Forever owns the scenario and generic optimizer only:** it requests native available alternatives for the class/level/spec/scenario, proposes and recombines gear × enchants × talents × APL candidates, asks the selected pinned native engine to prepare/validate/execute whole builds, and scores/searches actual results. No permanent Python GameIR, copied SQLite item source, class-specific Python talent eligibility or duplicate Warcraft game-rule catalogue. Retired P1/P2-only code is deleted, not rebuilt as a new Rust/Python proof pipeline. Migrate *live* P3–P7.5/optimizer consumers without breaking them before deleting transitional dependencies. The currently approved Go execution alternative is not silently outlawed by the Rust-owned target architecture.

**v7 governs game-fact ownership, not the current acceptance costs.** v8's active acceptance is defined in the current PROCESS and gate contracts; no new gate or duplicate MythicSim validation is introduced.

## Owner-approved v6 scope amendment (2026-11-03)

Retire P1 ability and P2 talent gates from formal checkpoint acceptance. The active acceptance set is P3–P6 plus P7.1–P7.5 (nine gates per checkpoint, 1,332 active checkpoint-gate pairs). The 148 checkpoint identities and user-facing product goal are unchanged. MythicSim remains the authority for spell/talent availability, legality and effects; those facts are consumed by active production paths without separate P1/P2 acceptance. Existing P1/P2 ledger entries remain historical and do not count toward current M1 or checkpoint completion. This was the scope decision at v6; current v8 gate predicates supersede older acceptance conditions.

## Product goal

Build a generic, source-driven WoW Forever 1–60 solo leveling simulator/optimizer for all nine classes. Given class, level, legal constraints and a pinned Forever ruleset, automatically discover and explain the best **known executable** combination of talents, equipment, combat/rotation policy, pull strategy and paid recovery/survival. Optimize comparable **real elapsed time per mob/route**, not only DPS, arbitrary XP proxies, or a preset guide build.

A user must be able to inspect actual selected gear with item identities and scored alternatives; talent ranks and next talent; the actual legal actions/rotations and their measured score; stat weights; encounter, survival and recovery; and why the chosen configuration beat benchmark alternatives. The engine must be generic; game facts and the optimizer's available alternatives come from the exact-SHA-pinned MythicSim Rust source of truth, not class-specific Python catalogues or hardcoded winner builds.

## Current first DONE DONE target — 148 certified checkpoints

**148/148 checkpoints independently accepted under the approved PROCESS's active P3–P7.5 gates (P3–P6 and P7.1–P7.5; nine per checkpoint)**:

- Nine classes × levels **20, 30, 40, 60** unrestricted = **36**.
- Druid **four** spec/profile constraints × four levels = **16**.
- Other eight classes **three** spec/profile constraints × four levels = **96**.
- **Total 36 + 16 + 96 = 148.**

Each accepted checkpoint includes source-legal real whole-build decisions, genuine 30s/300s timed search evidence, each distinct leveling winner's continuous 100-mob combat/recovery/survival, the approved P6 comparison, and the five pinned native-DPS P7 gates. Do not accept isolated action inventory, metadata, green unit tests or incompatible proxies. A diagnostic checkpoint is not DONE.

**Definition of first-phase DONE DONE:** exactly **148/148 accepted**, each with **nine genuine active gate PASSes** in the machine-readable register, 0 false-green entries. There is no separate checkpoint provenance certificate or hidden tenth gate. Final scorecard and reproducible artifacts published. This is the current working finish line; the historical 540 metric is not substituted for it.

## Broader product destination beyond the 148-checkpoint finish line

Eventually enable coherent outputs for **all nine classes × levels 1–60** (**540** class-level reports) and legal continuous 1–60 routes, including irrevocable talent choices, spell ranks, gear availability/acquisition, training/travel, cooldown and resource state across pulls, recovery and survival. Routes must be playable, not simple concatenations of independent per-level local winners. Explicit dual-spec/respec only under sourced rules. Track this separately from the 148/148 current checkpoint scoreboard; do not move the initial goalposts unilaterally.

## Immutable product constraints

1. No invented source facts, effect coefficients or talent spells; missing coverage clearly disclosed.
2. No class/spec winner presets or omitted legal action by unsupported-whitelist logic. The system searches source-derived alternatives and measures actual executable policies.
3. Optimize continuous actor and paid recovery/survival, with honest simulator fidelity/uncertainty.
4. Comparisons are on consistent character level, target/encounter, ruleset version, scenario and scorer; legacy references held out from search.
5. The final result must be inspectable and independently reproducible.
6. Completion is a counted validated *user-facing capability*, not release number, elapsed engineering hours, test count or source-scrape volume.
7. One Warcraft game-data/rules authority: pinned MythicSim Rust supplies candidate options and decides whole-build legality; Forever owns generic exploration and scoring without a replacement GameIR.

## Subordinate editable execution instruments

**MILESTONE PLAN:** decomposes the objective into the smallest number of outcome-sized verifiable milestones, orders the critical path, revises estimates and dependencies when evidence changes.

**MILESTONE IMPLEMENTATION PLAN:** chooses concrete implementation slices, reuse/refactor strategies, time budgets, validations, caching, automation and which action each W should perform. Optimize for **minimum total useful W cycles, model tokens and elapsed wall time**. Replan freely when a better path is supported, while preserving PROCESS and OVERALL PLAN verbatim.

A milestone report can be updated by agents. A sacred-process or overall-goal change **cannot** be smuggled through a milestone update. New Process or Overall Plan versions require the user's explicit request/approval; preserve this document as-is once approved.

## Current known planning state

As of the source records inspected 2026-10-15, strictly certified coverage was **0/148**, with earlier Druid L20/L30 results retained as diagnostic/previous-contract evidence rather than deleted. Those states are temporal bookkeeping, not permanent plan definitions. The current priority set by user is Druid L20 → Druid L30 → Mage L30; subsequent order and slices belong in the editable milestone plan.

## Approval record

- This v5 text was drafted following the user's explicit governance instructions on 2026-10-15.
- **v6 owner-approved 2026-11-03:** retire P1/P2 formal acceptance; keep 148 checkpoint identities and the remaining nine active gates.
- **v7 owner-approved 2026-11-04:** pinned MythicSim Rust supplies available optimizer alternatives and owns game-data/legality; Forever handles scenario/search/scoring, removes GameIR and redundant source rules.
- **v8 owner-approved 2026-11-04:** remove redundant P3–P7 proof and search costs while preserving the same nine gates, 148 checkpoints, native engine and genuine leveling/DPS results.
- **v9 owner-directed 2026-11-08:** one native Rust 2D combat/world/recovery evaluator per candidate; Forever Python owns end-to-end 1–60 route and old decision questions (fastest leveling spec, healer/tank main-role regret, best two level-40 dual specs and healer/tank second-spec regret). No change to nine active gates or M1 counts.
- All approved revisions require the user's explicit authorization; historical approval texts are retained in Git history.