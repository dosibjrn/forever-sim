# WoW Forever — OVERALL PLAN v14 (OWNER-DIRECTED)

**Date:** 2026-11-11  
**Status:** **OWNER-DIRECTED.** v14 assigns the direct Rust API to M0.3, the genuine sparse one-call optimizer result to M0.4, and progressive densification **20 → 10 → 5 → 1** of that *same optimizer* to M0.5; v13 requires parameterized wide-to-dense performance optimization with charged full-resource sample recovery; v12 makes official M1 PASSes permanent until 148/148, starts self-driving execution during M0.5, and requires reusable native observations. v11 separates useful route delivery from 144-gate certification and removes P4 cast-proof paperwork. v10 adds M0.6: an autonomous one-invocation source-native Decisions-style optimization pipeline; v9 defines M0.5 Warlock and free dual-spec optionality, v8 retains acceptance rules, v7 the single-source architecture and v6 the retirement of P1/P2. Git history contains earlier approvals.
**Purpose:** Define WHAT is built, the end-state and precisely when DONE DONE occurs. No gate implementation procedure or changeable milestone ordering belongs here; those live in PROCESS and milestone plans.

## Owner-approved v13: parameterized Decisions-style route optimization, not first-legal simulations (2026-11-10)

**One optimizer, tunable resolution.** A **single high-level invocation** accepts `start_level`, `end_level`, `level_stride` (or explicit sampled levels), `mob_count`, compute/search budget and scenario/ruleset. A first wide/sparse configuration is `start_level=20, end_level=60, level_stride=10, mob_count=3`: optimize L20, L30, L40, L50, L60 **together in one optimizer request**. The dense/full configuration uses the **same optimizer**, `start_level=10, end_level=60, level_stride=1, mob_count=100`. Stride and target count are *parameters*, not separate workflows, modes, milestones, special-case algorithms, or M1 gates. One high-level optimizer call may orchestrate many pinned Rust/native evaluation calls internally; it does not mean one Rust combat invocation for every level/build.

**Normalize the small-mob objective by fully paid terminal recovery.** Every candidate's `mob_count` native hostile pulls are followed by genuine source-native **recovery to full HP *and* full mana**, charging **all** simulated time and consumables. Optimize `combat + movement/pulls + survival + terminal recovery-to-full`, not raw DPS, kill time or a free reset. Let the optimizer choose legal Life Tap (HP→mana), eating, drinking and passive regeneration according to the available actor/spells/consumables and actual engine rules; iteratively account for both resources (Life Tap may improve mana while reducing HP). **No hypothetical instant full refill or fixed free aftercare.** If native behavior cannot complete or observe restoration, report the precise inability and an unscored/provisional candidate. This paid full-recovery boundary makes short native combat samples comparable without implying a character-level world/XP replay.

**Optimize across choices and sampled levels, not just simulate legality.** On each selected level, search multiple Rust-valid Affliction/Demonology/Destruction/hybrid talents and compatible talent paths, equipment, pets, APL/DoT/pull policies and recovery choices. The backend's deterministic `balanced` mode uses **one iteration/repeat per candidate by default** for search; additional balanced repetitions are not independent stochastic confidence samples. Within the compute budget, retain competing cross-level build frontiers and rank them using actually charged native elapsed combat/recovery time and source-native legal sampled-level compatibility. Sparse-level winners are provisional guideposts, not automatically complete talent paths. As budget allows, increase level density, mob count, candidate breadth and finalist validation **without changing optimizer architecture**. Longer or stochastic checks are decision-driven (or independently required by unchanged M1 contracts), not serial default 100-mob payments for the first native-preparable build.

**Evidence and compute:** A first-preparable talent addition, greedy full-tree fill or single native 100-mob run is a **baseline/feasibility observation**, not an optimized build. Preserve and reuse original genuine paid L20–L60 baseline receipts and the bounded greedy L47 family comparison; never re-pay them solely for more coverage. Reports identify evaluated levels, actual build/path alternatives and dimensions, `mob_count`, source/binary, `balanced` iteration count, terminal HP/mana, paid recovery time, scorer, elapsed score, baseline delta and missing mechanics/stat weights. Say "best of tested candidates" unless stronger evidence exists. This decision does **not** change any of the nine M1 gates, invalidate permanent recorded PASSes, or create an extra acceptance requirement.

## Owner-approved v12: permanent PASS and route-first automation (2026-11-10)

**Once officially accepted, always accepted until 148/148.** Each genuine M1 PASS recorded by Merge's approved production recorder is final, cumulative progress toward the 148 certified checkpoints. Never revoke, invalidate, reopen, recompute, or rerun that accepted gate because a newer engine/source SHA, code/contract/optimizer refactor, interface change, later result, compatibility claim, or regression affects today's implementation. Its original measured acceptance remains valid for the project goal. A new discovered production defect is fixed and tested as a **new defect**, without retroactively questioning or deleting the already accepted historical PASS. A merely green workflow, unrecorded diagnostic, or PARTIAL is not an officially accepted PASS. No new retroactive audit or provenance certificate is authorized.

**Build autonomy while earning M0.5 results.** M0.6's generic self-driving Forever/gsim orchestration begins during M0.5, not after all L10–60 levels are manually processed. Once two successive levels use the same native protocol, expand through one parameterized, resumable level-range driver that discovers Rust options, prepares legal candidates, executes and retains paid scenarios, optimizes, and updates measured/provisional route output. Do not make a new per-level workflow, separate PR or human trigger the default way to advance. Publish the best-known guide immediately with honest coverage; neither M0.6 automation nor M1 certification blocks that publication.

**Reusable paid native observations.** An actually executed native result is immutable evidence for its original scenario. Automatically reuse completed or in-flight compatible work across agents, levels, candidate comparisons, guides and eligible M1 gates using exact native engine/source, build/actor start state, scenario, seed/RNG, recovery and execution-protocol identity. Execute only genuinely missing, changed or contractually independent work; preserve mandatory independent cold searches/holdouts when a gate explicitly requires them. This is an optimizer/runtime cache and provenance mechanism, **not** a new acceptance gate, second M1 ledger, or reason to question an accepted PASS.

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

## M0.3 — Direct native Rust API (owner-approved 2026-11-11)

**Outcome:** Forever consumes the pinned MythicSim Rust game options, whole-build preparation and native real-world simulation/recovery through a direct typed callable interface or persistent request/response session. Do not create source/prepared JSON intermediate files per candidate, execute a new CLI process for every candidate, or add parallel Python Warcraft legality implementations. JSON remains acceptable as a wire format and for final saved results, not as file-based orchestration.

**Scope:** Class/level/ruleset/scenario-parametric native `get_options`, `prepare` and `evaluate` must expose usable gear, enchant, talent, spell and APL alternatives, accepted/refused whole builds, gsim↔Rust spatial-world ACK execution and genuinely paid terminal recovery to full health **and** mana. Native Forever options exclude items with combat-rating stats (not a Forever stat), and retain native percent stats as percent, with no rating conversion. One rejected item drops that candidate, not the entire search. Verify real native results and errors through a focused integration run; do not compare Rust's deterministic-protobuf SHA against JSON-file SHA or create extra result-acceptance gates.

**Boundary:** M0.3 is the reusable engine API, **not** the first successful optimized multi-level outcome. That is M0.4. Source-native game rules and option legality stay in Rust for every class; no Warlock-only API or hardcoded winner.

## M0.4 — First genuine successful generic optimize invocation (owner-approved 2026-11-11)

**Exact required one-command delivery:**

```bash
python -m src.v2.runner optimize \
  --class warlock \
  --tree unconstrained \
  --start-level 20 \
  --end-level 60 \
  --level-stride 20 \
  --n-mobs 2 \
  --recover-at-end true \
  --rng balanced \
  --backend rust
```

**Completion means this command runs successfully using the M0.3 API and real pinned Rust + gsim/native execution**, without manually launching subruns, supplying known winners, inserting a Warlock-specific orchestration script or switching to a mocked evaluator. Within the same optimizer request it searches actually competing talent families/hybrids, equipment, pet and APL/pull/recovery policies at **L20, L40 and L60**, including cross-level/backward seeding, and produces **at least one complete mutually compatible measured sampled-level build path**. Preserve slower early candidates when later-level cumulative performance can make their paths better. The reported output includes per-level talents, actual gear item identities, pet, APL, scored alternative builds, genuine two-mob combat/movement elapsed time, real terminal recovery to **100% HP and 100% mana**, and authentic engine/scenario receipts. Neither a first-legal build nor three independent per-level winners is optimization.

**Level stride is sampling, not a demand to simulate skipped levels.** Do not run or require combat or preparation at L21–39 or L41–59 for the stride-20 request. Sampled-compatible talent allocations must follow source-native legal point investment with no invented respec; unmeasured levels are explicitly unmeasured, not fabricated as sampled combat. XP accumulation, training and between-level travel are **outside M0.3–M0.6 scope**. The same generic optimizer supports other classes, strides, mob counts and budgets as parameters, not distinct algorithms.

**No false-green outcome:** unit tests, mock results, green CI without genuine native combat, exit code zero with no winner, an empty `NO_COMPLETE_COMPATIBLE_SAMPLED_PATH` result, unranked/refused candidates or an SHA-identity paperwork check do **not** satisfy M0.4. Reuse already-paid compatible observations; retain precise native error reasons and continue over other valid item/build candidates. M0.4 delivers a real sparse result; M0.5 densifies its measured compatible sampled Warlock L20–60 build guide; M0.6 autonomously orchestrates the same candidate search, native validation and reporting with one invocation. No new M1 gate or change to permanent accepted PASSes.

## M0.5 — Progressive density of exactly the M0.4 generic optimizer (owner-approved 2026-11-11)

**M0.5 is the same callable product as M0.4 with `level_stride` refined from 20 to 10, then 5, then 1.** The class, source backend, candidate discovery, joint search, legal sampled talent-path compatibility, paid combat + movement + full HP/mana recovery objective and output schema are exactly unchanged. Start level **20 is fully acceptable**; L10–19 is not a prerequisite and M0.5 is not a different full-route algorithm. Keep `end_level=60`, `n_mobs=2`, `rng=balanced` as valid configurations; budget may scale with sampled levels. No per-level workflows, Warlock-only evaluator, handcrafted JSON route, mandatory skipped-level prepare or new tests/certificates for changing stride.

**Critical engine prerequisite for densification:** the pinned Rust source currently natively prepares Troll Warlock at L20 and L60, but its `prepare/character.rs` refuses other L21–59 levels. M0.5 requires a source-backed **general 20–60 Warlock actor-level preparation capability** (no per-level hardcoded fixtures or fake extrapolated gameplay), so stride=1 can actually simulate all 41 requested levels. Fix this capability in Rust during M0.3/M0.4 work and keep unprepared levels explicitly unsupported until real native preparation executes; a single L40 hack is insufficient. Do not add intermediate preparation as a prerequisite for M0.4's stride-20 samples.

**Delivery steps, in order within the same optimizer:** after M0.4's demonstrated L20/L40/L60 result at stride=20, execute a real `optimize` at stride=10 (L20/30/40/50/60), then stride=5 (L20/25/30/35/40/45/50/55/60), then stride=1 (all L20–60 levels). Each step must return at least one **genuinely source-native measured, jointly compatible ranked path** at every requested sampled level, with selected talent allocations, item identities, pet, APL/pull/recovery policy, competing native observations, true elapsed time including two-mob final restoration to both full HP and full mana, plus honest refusals/limitations. Reuse identical paid candidate/scenario observations across densification and cross-seed previous promising complete paths instead of restarting search. Iterate budget and frontier breadth to obtain real competition, not first-legal baselines.

**Definition of success:** same production entry point, no new special mode, and actual measured compatible paths through all four requested strides. A green test, an empty path or independent per-level winners are not M0.5 completion. At stride=1, all L20–60 levels are sampled, but that is **not** proof of an XP, travel or training replay; **such a replay is not required for M0.5 or M0.6**. The published Warlock build guide and M1's independent acceptance gates may improve in parallel, but **neither is an extra prerequisite** for M0.4/M0.5's measured optimizer deliverable. Preserve immutable existing M1 gate contracts and accepted PASSes.

## M0.6 — One-run autonomous Decisions-style optimization and answer (owner scope clarified 2026-11-11)

**Goal: one user invocation, no manually orchestrated subruns.** Extend the existing M0.4/M0.5 generic Forever/gsim optimizer into a self-driving Decisions-style workflow. Given a class, sampled level range/stride, scenario, ruleset, constraints and compute budget, **the software itself chooses which source-native candidates to test next**; it must not require manual L20/L30/L40/L60 runs, separate gear/talent/APL/pet searches, hand-selected winners, manually dispatched 100-mob validation or manual report stitching. One invocation may make many genuine pinned Rust calls. This is autonomous **search and report generation**, not a new Warcraft progression simulator.

**Required automatic work:** discover native options; generate multiple legal talents, gear, APL, pet, pull and paid-recovery candidates; reuse compatible original native results; adaptively allocate short and longer paid combat tests; compare genuinely measured elapsed time including movement, survival and final recovery to **full HP and mana**; retain multiple legal compatible sampled-level build paths, including optional dual-spec/single-spec comparisons when the selected native rules support them. Automatically verify contenders using real native combat and publish ranked alternatives, source/engine/seed identities, per-level decisions, original receipts and a useful human-readable Warlock guide. Source-backed level compatibility must be checked; untested level/build combinations stay unmeasured.

**Explicit exclusion:** M0.6 does **not** require XP accumulation, character level-up events, trainer visits, between-level travel, persistent actor state across levels or a single continuous 10–60 game-world/XP replay. It does **not** require one long Rust Fight joining separately sampled levels, and such continuity must not be invented or claimed. **Native combat within each sampled encounter and its actual charged recovery remain mandatory.** Cross-level optimization is over a legally compatible sequence of measured build snapshots, not a continuous XP timeline. These excluded capabilities must not block M0.6, be assigned as M0.6 prerequisites or create new acceptance gates.

**Acceptance:** from a clean checkout with compatible pinned Rust and scenario data, **one documented CLI/API call** autonomously performs candidate discovery, paid native evaluations, adaptive selection, finalist verification and report publication without human intervention or supplied winner builds. A targeted integration test proves the high-level invocation calls real native combat/recovery and produces inspectable ranked output; a bounded paid multi-level run demonstrates the full orchestration. Publish budget, native evaluation counts, level/stride coverage, alternatives, exact engine/source identities and unsupported dimensions. Never pass mocks, a cached-only answer or an unranked first-preparable candidate off as genuine optimization. Keep the implementation generic for all nine classes; do not add a parallel Python Warcraft mechanics model.

**Relationship to M0.5 and M1:** M0.5 remains the same optimizer sampled at strides 20 → 10 → 5 → 1. M0.6 automates its search, evaluation, selection, reuse and reporting in one call, **without an XP/travel/training/continuous-replay deliverable**. M1 keeps its separate nine accepted active gates per checkpoint and immutable recorded PASSes; M0.6 never grants or reopens an M1 PASS.

## Current first DONE DONE target — 148 certified checkpoints

**148/148 checkpoints independently accepted under the approved PROCESS's active P3–P7.5 gates (P3–P6 and P7.1–P7.5; nine per checkpoint)**:

- Nine classes × levels **20, 30, 40, 60** unrestricted = **36**.
- Druid **four** spec/profile constraints × four levels = **16**.
- Other eight classes **three** spec/profile constraints × four levels = **96**.
- **Total 36 + 16 + 96 = 148.**

Each accepted checkpoint includes source-legal real whole-build decisions, genuine 30s/300s timed search evidence, each distinct leveling winner's continuous 100-mob combat/recovery/survival, the approved P6 comparison, and the five pinned native-DPS P7 gates. Do not accept isolated action inventory, metadata, green unit tests or incompatible proxies. A diagnostic checkpoint is not DONE.

**Definition of first-phase DONE DONE:** exactly **148/148 accepted**, each with **nine genuine active gate PASSes** in the machine-readable register, 0 false-green entries. There is no separate checkpoint provenance certificate or hidden tenth gate. Final scorecard and reproducible artifacts published. Every official PASS is counted permanently when first accepted; the 148/148 result is cumulative across accepted engine revisions and does not require final-version revalidation of earlier checkpoints. This is the current working finish line; the historical 540 metric is not substituted for it.

## Broader product destination beyond the 148-checkpoint finish line

Eventually enable coherent outputs for **all nine classes × levels 1–60** (**540** class-level reports) and legally compatible sampled-level build paths, including sourced talent choices, spell ranks, available gear, pull/recovery policies and optional dual-spec/respec only when supported by native rules. Keep missing or unsimulated decisions explicit. This broader coverage target is separate from both M0.6's autonomous orchestration and M1's 148/148 checkpoint scoreboard; do not add world/XP replay prerequisites or move initial goalposts unilaterally.

## Immutable product constraints

1. No invented source facts, effect coefficients or talent spells; missing coverage clearly disclosed.
2. No class/spec winner presets or omitted legal action by unsupported-whitelist logic. The system searches source-derived alternatives and measures actual executable policies.
3. Optimize native-paid combat, recovery/survival and legally compatible sampled-level build paths, with honest simulator fidelity/uncertainty.
4. Comparisons are on consistent character level, target/encounter, ruleset version, scenario and scorer; legacy references held out from search.
5. The final result must be inspectable and independently reproducible.
6. Completion is a counted validated *user-facing capability*, not release number, elapsed engineering hours, test count or source-scrape volume.
7. One Warcraft game-data/rules authority: pinned MythicSim Rust supplies candidate options and decides whole-build legality; Forever owns generic exploration and scoring without a replacement GameIR.

## Subordinate editable execution instruments

**MILESTONE PLAN:** decomposes the objective into the smallest number of outcome-sized verifiable milestones, orders the critical path, revises estimates and dependencies when evidence changes.

**MILESTONE IMPLEMENTATION PLAN:** chooses concrete implementation slices, reuse/refactor strategies, time budgets, validations, caching, automation and which action each W should perform. Optimize for **minimum total useful W cycles, model tokens and elapsed wall time**. Replan freely when a better path is supported, while preserving PROCESS and OVERALL PLAN verbatim.

A milestone report can be updated by agents. A sacred-process or overall-goal change **cannot** be smuggled through a milestone update. New Process or Overall Plan versions require the user's explicit request/approval; preserve this document as-is once approved.

## Current known planning state

As of the source records inspected 2026-10-15, strictly certified coverage was **0/148**, with earlier Druid L20/L30 results retained as diagnostic/previous-contract evidence rather than deleted. Those states are temporal bookkeeping, not permanent plan definitions. That Druid L20 → Druid L30 → Mage L30 priority was historical. The owner-selected immediate priority is **M0.3 API → M0.4 stride-20 actual native optimize → M0.5 stride 10 → 5 → 1**; concrete work dispatch remains in the editable milestone/priority plan.

## Approval record

- **v14 owner-approved 2026-11-11:** M0.3 is the direct generic Rust options/prepare/evaluate API with native Forever-only item stats and no file/SHA false gates. M0.4 is complete only when the exact `python -m src.v2.runner optimize --class warlock --tree unconstrained --start-level 20 --end-level 60 --level-stride 20 --n-mobs 2 --recover-at-end true --rng balanced --backend rust` invocation returns genuinely scored, mutually compatible L20/L40/L60 builds. M0.5 is the identical optimizer progressively refining stride 20 → 10 → 5 → 1 with start-level 20 acceptable. M0.6 is the fully automatic one-invocation optimizer/report, **not** XP/travel/training/continuous native leveling replay (scope clarified by the owner 2026-11-11). M1 existing certifications remain independent. No new M1 predicates.

- This v5 text was drafted following the user's explicit governance instructions on 2026-10-15.
- **v6 owner-approved 2026-11-03:** retire P1/P2 formal acceptance; keep 148 checkpoint identities and the remaining nine active gates.
- **v7 owner-approved 2026-11-04:** pinned MythicSim Rust supplies available optimizer alternatives and owns game-data/legality; Forever handles scenario/search/scoring, removes GameIR and redundant source rules.
- **v8 owner-approved 2026-11-04:** remove redundant P3–P7 proof and search costs while preserving the same nine gates, 148 checkpoints, native engine and genuine leveling/DPS results.
- **v9 owner-approved 2026-11-09:** add M0.5 Warlock first and clarify that free optional dual spec weakly dominates single-spec (but sourced acquisition/switching costs can change net optimal adoption); preserve the v8 acceptance scope.
- **v10 owner-approved 2026-11-09:** add M0.6 autonomous, one-invocation Warlock 10–60 Decisions-style native optimizer (no manual subrun triggers); retain M0.5 outputs and unchanged M1 acceptance/governance.
- **v13 owner-approved 2026-11-10:** One parameterized, deterministic-balanced, performance-ranked 10–60 Decisions-style optimizer; sparse levels 20/30/40/50/60 and 3 mobs are parameters, dense stride-1/100-mob is the same optimizer; charge native full HP+mana recovery after every measured sample, including Life Tap/eating/drinking as legal; no serial first-legal paid route as optimization.
- **v12 owner-approved 2026-11-10:** once formally recorded, M1 PASS never expires or requires retesting before 148/148; develop M0.6 automation concurrently with M0.5; reuse compatible paid native observations automatically; make user-facing capability rather than per-level PR count the delivery target.
- **M0.6 owner clarification 2026-11-11:** remove XP accrual, training/travel, persistent cross-level actor state and continuous game-world replay from M0.6 requirements; retain one-invocation Decisions-style native-paid build optimization, validation and reporting. Historical wording is available in Git history.
- All approved revisions require the user's explicit authorization; historical approval texts are retained in Git history.