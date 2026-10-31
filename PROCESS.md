# WoW Forever — PROCESS v2.10 (APPROVED; FULL CONSOLIDATED CONTRACT)

**Date:** 2026-10-30  
**Status:** APPROVED. Rust is preferred and Go equally acceptable. On 2026-10-30 the owner explicitly removed the one-sided 95% confidence-bound PASS rule from P7.5; holdout **mean DPS** is the acceptance statistic. All other gate constraints remain unchanged.  
**Supersedes:** canonical PROCESS v2.9, retained in Git history; avoid numbered sibling copies.  
**OVERALL PLAN:** canonical `OVERALL_PLAN.md` v5 remains immutable (previous versioned copy preserved in Git history); its original Decisions P7 wording is inconsistent with this revised PROCESS. A matching v7 update is only a PROPOSAL until separately approved. This discrepancy is disclosed, NOT silently reinterpreted.  
**Unchanged:** P1–P6 definitions, 148 checkpoints, 30s/300s independent leveling searches, N300 breadth, continuing 100-mob combat+recovery, P6 1% saturation, backend-neutral P1/P2 and event ownership.  
**Changed in v2.8:** Saved MythicSim report UI/Settings is authoritative for exact references; raw API JSON is optional.  
**Changed in v2.9:** Select genuine pinned MythicSim **Rust (preferred)** or **Go** for combat, including native parity, live 2D integration and stochastic holdout.  
**Changed in v2.10 (issue #10):** P7.5 PASS uses **the independently frozen stochastic holdout's mean DPS**, not a one-sided 95% confidence-bound lower limit. Compare with the full saved external reference DPS and 99% of the **strongest accepted, compatible** P7.1–P7.4 stochastic mean. Preserve >=1,000 holdout fights, cold <=300s search, actual source legality, and live 2D↔native causality. Do not substitute unvalidated prior results for the accepted comparator.  

## Git-controlled gate promotion and canonical process files

Approved by the user on 2026-10-29. Git is the version history; do not create dated or version-numbered copies of the process artifacts in this repository.

- Canonical documents on `main`: `PROCESS.md` (this contract) and `OVERALL_PLAN.md` (product goals). Update these files in place through reviewed commits; rely on Git commits and tags for provenance.
- Develop each implementation gate in an isolated branch. Keep unaccepted work out of `main`.
- After **each individual gate** meets its existing documented acceptance criteria, commit the exact evidence (tests, source revision, simulation output and comparisons), and merge that completed gate to `main` before starting the next gate promotion. A green build alone does not qualify as a P7 PASS.
- Do not mix pending or failed gates in a passing-gate merge. Preserve the previous checkpoint count and gate scoreboard until evidence justifies a change.
- The user may explicitly approve governance changes; change canonical documents via Git commits rather than creating sibling numbered documents. Historic approved versions remain retrievable from Git history.
- Existing P1–P7 acceptance tests, thresholds, 148-checkpoint definition and engine parity requirements are unchanged.

## 1. Immutable governance

The project has two **sacred**, user-controlled documents:

1. **PROCESS** defines HOW work is done: rules, gate criteria, evidence, workflow, model architecture invariants and approval practice.
2. **OVERALL PLAN** defines WHERE the project is going: desired user outcome, scope and the exact DONE DONE definition.

**Neither document may have its substantive governance changed without the user's separate, explicit request or approval. Approved changes update the canonical Git-tracked file in place; Git preserves history.** If a new requirement conflicts with one of these documents, show the difference and seek authorization for a new, immutable version. Do not silently modify history. Record approval, version and SHA-256 in handover. Any lower-level document conflicting with the sacred documents loses.

**MILESTONE PLAN** and **MILESTONE IMPLEMENTATION PLAN** are subordinate, **mutable** instruments. Agents may revise their work breakdown, priority and implementation strategy to reach OVERALL PLAN's DONE DONE in the fewest useful W rounds, shortest wall-clock time and lowest reasonable token cost. They may not change PROCESS or OVERALL PLAN's goals or pass criteria.

Authority: explicit user instruction → approved PROCESS and OVERALL PLAN (each within its respective remit) → current milestone plan → milestone implementation plan → release/handover → historical evidence. When user decisions affect a sacred document, obtain explicit approval and update the canonical document through a recorded Git commit, preserving prior versions in Git history.

## 2. One truthful scoreboard; 148 checkpoints

The initial exact acceptance register has **148** checkpoints: 36 unrestricted = nine classes × levels 20, 30, 40, 60; 112 spec-constrained = Druid four profiles × four levels (16) and the other eight classes three profiles × four levels (96). The order is determined by the OVERALL PLAN, not invented inside a W round. A checkpoint counts only if **P1–P6 and P7.1–P7.5 all PASS** on the same pinned ruleset and compatible production engine semantics. P1–P6 use the pinned continuous 100-mob leveling objective; P7.1–P7.5 use the *same production integration* in the separate pinned MythicSim DPS-reference scenario. The different objective is explicit, never disguised as a 100-mob result. Stale, partial, synthetic, proxy-only or blocked evidence never counts as PASS. Report both actual accepted count and remaining blocker.

P1–P6 and the five named P7 subgates are the approved gates; **no additional hidden gate** may be introduced. A chosen source ingestion technique, full external catalogue scrape, raw-byte attestation, perfection of every item effect, or elaborate verification methodology is not an additional P3 prerequisite. Better source completeness is desirable backlog work, not automatically an acceptance veto.


### Backend names and checkpoint acceptance (USER-REVISED 2026-10-26)

- **`dsim` = legacy Decisions**: historical optimizer and optional diagnostic challenger, no longer the mandatory P7 reference; not automatically a P1/P2 production executor.
- **`gsim` = Generic Sim**: existing source-backed GameIR/CombatRuntime, 2D world and continuous chainpull.
- **`msim` = MythicSim**: selected genuine pinned **Rust or Go** combat/spell/talent/resource engine; Rust preferred, Go fully valid. **`hybrid` = selected native MythicSim executor + actual gsim 2D world/controller**, one shared monotonic clock and strict event ownership. Do not splice engine outputs or treat untested APIs as integrated.
- The unchanged public gate entry point is `python tools/wf_gate.py --class <class> --level <level> --gate P1` (and P2–P7.5). Without requiring a new flag, show available `gsim`, `msim-rust`, `msim-go`, selected live `hybrid`, evidence provenance and blockers. An unavailable alternative is not a blocker for a passing selected executor.
- **Per-gate P1/P2**: genuine source-legal, behavior-tested execution on `gsim` OR selected `msim-rust`/`msim-go` (live hybrid when world-dependent) can satisfy the gate. Do not reimplement known-good effects just to support a second engine. A fabricated union of incomplete implementations cannot PASS.
- **Per-checkpoint P1–P6, P7.1–P7.5**: all gates require a mutually compatible, actually executed production pipeline on the SAME pinned source, ruleset and combat semantics; P1–P6 share their leveling objective, and the five P7 subgates share one separate pinned single-target DPS objective; different scores or semantics cannot be spliced across backends. A gsim-only PASS remains valid until displaced by real successor evidence. Diagnostic backend differences are recorded but do not automatically fail a passing backend.
- Any reported `PASS` must identify exact evidence kind (`native-msim-rust`, `native-msim-go`, `gsim`, `hybrid-rust`, `hybrid-go`, or external reference), real source/runtime/database/config hashes and executed behavior. A compile, registration, mock, synthetic 2D or replay-only trace is not a PASS.
- **Ownership**: selected native MythicSim Rust/Go engine owns combat hit/damage/heal, resource, cooldown, talent, spell and gear effects it actually implements; gsim world owns geometry/facing/range, pulls, movement/CC and world-side behavior. One shared event chronology; no duplicate mechanics. Native pushback etc can count if behavior-tested without reimplementation.
- Native Rust/Go single-fight runs can support isolated P1/P2 and P7.1.2 but do not replace continuous 2D combat/recovery/survival in P4–P6 or live gsim-2D↔native feedback for P7.1.3/P7.2–P7.5. The owner's individually accepted historical Balance L60 P7.1 Rust result remains CLOSED, with its absence of Go/live-2D evidence disclosed; it does not waive other/new production obligations.

## 3. Gate definitions

### P1 — Legal abilities and ranks

Source-derived legal/conditional actions at the checkpoint level, correct ranks and prerequisites, represented in common GameIR and available to candidate generation; explicitly report unresolved cases and meaningful inability to execute a relevant ability. Never silently prune a legal action based on class or supported-effect whitelist. Do not equate an L0 source label with correct L2 execution.


**Observable P1 impact on selected backend (USER-REVISED 2026-10-26):** The canonical source-derived legal/conditional ability denominator remains unchanged. A source-legal, relevant ability must be usable by candidate generation and must show its applicable effect through the **real selected production executor** in an appropriate precondition/target/form/range/resource scenario. Evidence can be a target HP change, real DoT ticks, heal, stat/resource change, aura that actually influences a stat/action, CC-afflicted movement/behavior, interrupt, pushback, pet action, or analogous mechanical consequence. Mere registration, successful cast counter, effect metadata, synthetic stub event or inactive aura is NOT proof. Trigger conditional abilities in a suitable situation; if not actually tested, report a concrete unresolved condition, not a silent PASS. For a spell with multiple relevant independent effects, test its applicable effects without requiring one universal DPS delta. A deterministic paired positive/negative control or an equivalent targeted behavioral assertion is sufficient. Never demand a 100-mob run **per spell** as an additional P1 gate. Highest level-legal rank is sufficient where the pinned P1 scope excludes downranking; retain legal granted abilities. A reachable legal spell absent from gsim but present and behavior-tested in msim/hybrid is P1-covered on the msim path.

### P2 — Talent legality and effects (USER-REVISED 2026-10-16: IMPLEMENTATION + TESTS, BINARY)

A talent rank has **exactly one acceptance state**: `PASS` or `FAIL`. The complete source-derived, structurally reachable rank set is the P2 denominator; do not silently exclude inconvenient ranks or actions.

A reachable rank is **PASS** if and only if all of the following are true:

1. **Legal allocation works**: its point-budget, tier, prerequisites, form/level restrictions and rank application succeed using the canonical talent representation.
2. **Suitable implementation exists**: the described effect/unlock/condition has a real implementation through the selected production backend (`gsim`, `msim`, or the integrated `msim+gsim-world` path); it changes the applicable observable gameplay state/event/action availability. A placeholder, silent no-op for an applicable effect, or a rank that is merely accepted structurally is insufficient.
3. **Behavioral tests PASS**: automated tests exercise the rank's actual applicable effect or unlock through the production implementation, checking a meaningful precondition and the expected outcome (including form/target/trigger and negative controls when applicable). The tests are deterministic where practical and run against the relevant pinned source data and executable runtime, not only isolated mocks or mere catalogue assertions.
4. **Search can use it**: legal allocations are not filtered out of candidate generation, and newly unlocked actions are represented so P4/P5 can genuinely execute them.

If one condition is missing, **FAIL** with a *concrete actionable defect*: e.g. `IMPLEMENTATION_MISSING`, `BEHAVIOR_TEST_MISSING`, `BEHAVIOR_TEST_FAIL`, `ALLOCATION_INVALID`, `SEARCH_ACTION_MISSING`. Fix the defect and rerun. A rank with multiple applicable effects needs appropriate implemented/tested behavior for each, but no independent provenance-essay or semantic-proof exercise.

**Explicitly prohibited as acceptance states, blockers or W work items:** `PARTIAL_SEMANTICS`, `SEMANTICS_UNVERIFIED`, `SOURCE_BRIDGE_UNVERIFIED`, "prove semantic parity", a source-version provenance bridge pursued in isolation, source archaeology to reconfirm already implemented/tested behavior, or additional talent-semantic proof rounds. Record uncertainty as informational metadata if helpful; it is **not an eighth gate and is not an automatic P2 veto**. A known failed test or an actually missing/incorrect implementation remains a genuine FAIL. Do not invent unavailable game data, fabricate a passing test, or hide a known contradiction.

**P2 GREEN** when **every** reachable rank is PASS under the conditions above, including prerequisite/allocation tests and real executor integration; no separate semantic certification is required. Group tests by generic effect family, parameterize rank differences, and reuse one working executor. A fast representative 100-mob smoke can catch cross-cutting runtime regressions, but running 100 mobs for each rank and repeatedly re-proving source semantics is not required by P2.

**Migration of old P2 reports:** Historical `129/129 executors, 14 partial semantics, one source bridge` does not by itself say either PASS or FAIL under this contract. For each formerly flagged rank, examine **only whether its real implementation and behavioral tests already satisfy the above predicate**. If yes, mark PASS immediately. Otherwise add exactly the missing implementation/test/legality defect and fix it; **do not spawn a new semantic-verification task**. Recompute the real P2 status on the merged current code and continue downstream gates as soon as GREEN.


**Observable P2 impact on selected backend (USER-REVISED 2026-10-26):** For each source-legal, structurally reachable talent rank, check legal acquisition and actual production behavior on `gsim` OR selected `msim-rust`/`msim-go` (live hybrid when world-dependent): compare the same legal setup **with versus without that rank** (or adjacent ranks and an explicit tested unlock/control), and assert at least one **causally appropriate** observable effect in the designed trigger scenario. The effect may change damage/healing, stats, costs, cast/cooldown, CC/survival, pet mechanics, or grant a usable new ability. Do not require a nonzero DPS difference where none should occur. The rank must be usable by source-derived allocation and search; unlocked spells must be executable in P4/P5 as defined there. Source-field access, talent-tree label, Go implementation filename and `notSimulated=false` are NOT substitutes for an actual behavioral test; do not label ordinary source uncertainty as a new semantic-certification gate. No double implementation requirement across backends. A rank with a known no-op/placeholder in its chosen executor is FAIL until a real implementation is used.

### P3 — Minimal, *fast* gear-scoring smoke test (USER-REVISED)

For **each equipment slot**, retrieve **up to five highest item-level (ilvl) items** in the currently available item database which the checkpoint character can legally equip (class, level, spec-related restrictions, weapon/armor/slot rules). The ranking used to *choose the five test items* is **ilvl**, NOT the computed item score. If fewer than five legal items exist for a slot, test the available items and record that count.

For every chosen item with ordinary stat fields, its generic, build-context gear scorer MUST return a finite numerical score, and its stat contributions MUST actually affect that score. All calculated ordinary gear stat weights, including those beyond the named categories, must be **non-negative (`>= 0`)** for any class/build. Do not mask a negative result by clipping or falsifying values. For these stat fields, when they occur in the tested legal gear, the corresponding meaningful context weight must be **strictly positive (`> 0`)**:

- Armor, Stamina, Spirit, Agility.
- Strength and/or Intellect as present and applicable.
- Attack Power (AP) and/or Spell Power (SP) as present and applicable.
- Crit, Hit, Dodge, Parry.
- Mana per five seconds (MP5), Health per five seconds (HP5).
- **Weapon DPS / Wand DPS / Ranged Weapon DPS are ALTERNATIVES**, not three required positives: at least ONE *applicable* equipped-weapon DPS channel must have a meaningful positive weight **only when the evaluated build and rotation can actually benefit from that weapon's damage channel**. A legal item existing in the slot by itself does NOT prove relevance. A positive weight in an unrelated weapon channel does not satisfy this requirement. **Explicit user-approved exception: caster Druid**, whose evaluated rotation does not depend on equipped-weapon melee/ranged/wand damage, requires NO positive Weapon/Wand/Ranged DPS weight; its weapon DPS weights may be zero. This exception may not be overridden by an automatically invented minimum positive epsilon.
- **Mean weapon hit damage** has an additional strictly positive weight **only** when the CURRENT evaluated rotation contains an actually executable attack whose sourced runtime damage depends on the **equipped item's min/max weapon hit damage**. Determine that causal link from generic sourced effects, form, selected combat-backend semantics and the actual rotation, **not class/spec hardcoding**. A generic `weapon_damage` effect label is insufficient if, for example, an animal form resolves it through normalized/feral form damage rather than the equipped weapon's min/max values. **Caster Druid with no equipped-weapon-dependent action is exempt.** Retribution Paladin, Warrior and Rogue are examples when their policies use real equipped-weapon-damage attacks, not unconditional class exceptions. Mean equipped weapon hit damage = (item min damage + item max damage) / 2.
- All ordinary stat weights remain **non-negative**. The user-approved exemption permits a mechanically irrelevant weight to be **zero**; it never licenses a negative weight, fabricated score, missing stat field or omitted test item. This changes P3 applicability only, not the P4/P5 requirement to actually test talent-unlocked spells.

An arbitrarily tiny positive epsilon added solely to satisfy the test is invalid. A displayed top-five-by-ilvl *test set* is not a claim that those five are the best-scoring gear. P3 is not a global Bis/gear-optimality certificate.

**P3 expressly does NOT require** a verified full Wowhead Forever item-level 1–255 class catalogue, proof that no item anywhere is missing, SHA256s of every source webpage, modeling every equipment proc/equip/on-use special effect, or 100-mob marginal perturbation per stat/item. Unsupported special effects may remain outside this smoke test; do not invent their values or treat uncertainty as fully modeled. Source improvement remains backlog, not a universal P3 RED reason.


**Backend applicability:** The unchanged P3 item/weight smoke criteria are evaluated with scores and mechanical applicability from the selected, real production build context. Gear and stat weights may come from gsim or selected Rust/Go msim/hybrid; do not require the old gsim scorer to simulate the same stat again if msim supplies executable effects and the optimizer consumes those weights. The requested source legality, finite values and non-negativity conditions remain binding.


**Backend applicability:** P4/P5/P6 preserve the precise wall-clock budgets, candidate breadth, 100-consecutive-mob and saturation criteria below. The optimizer may call gsim or the integrated msim+2D-world backend but the paid full-combat/recovery/survival outcome must be executed in the selected consistent runtime; mixing post-hoc native combat damage with unrelated gsim healing/regen clocks is invalid. Must preserve actor health/mana/resource, cooldowns, buffs, pets, movement/CC, survival and regeneration across pulls and the correct target-level rules. A smoke test on a single target, a mock binary, a replay-only bridge or a missing msim actor-level implementation is not P4–P6 acceptance evidence.

### P4 — Independent 30-second whole-build search, including talent-unlocked actions

Perform independent, cold, source-legal **gear × talents × generated rotation/policy × pull/recovery/survival** optimization within **30 actual wall seconds**, without seeding the previous/legacy winner. Record full configurations, real paid evaluations, and a complete **100 consecutive mob** combat+recovery+survival measurement of the chosen winner on the pinned objective.

**MANDATORY newly unlocked spell coverage:** if a reachable legal talent allocation grants/unlocks a new spell/ability, the search must automatically GENERATE and ACTUALLY EXECUTE/EVALUATE at least one legal policy/rotation containing that new action. Evidence must trace `talent allocation → unlocked action ID → generated policy → real runtime use/cast count > 0 → measured outcome → compared alternative`. Merely listing it in P1/P2, adding an unreachable APL condition or showing it in the candidate source inventory is **P4 FAIL**. The final winning rotation is allowed to exclude the unlocked spell if the actually executed alternative loses. Implement this with generic source IR and action-search logic, never manually class- or spell-specific rotation templates. If the time budget prevents this required coverage, report P4 FAIL, not a narrowed-universe PASS.

### P5 — Independent 300-second search

Repeat cold independent whole-configuration search on the SAME objective/source/legal space within **300 actual wall seconds**. Count unique, fully specified, legally and genuinely paid candidates rather than duplicate screens. Existing strengthened criterion: `N300 >= 10 × N30`, with at least one complete 100-mob finalist. P5 inherits the P4 rule for talent-unlocked spells. If the threshold or required source/runtime coverage is unmet, report FAIL/BLOCKED; any future change to the criterion requires explicit user approval to modify this PROCESS.

### P6 — Independent 100-mob saturation replay

Cold-replay both independently discovered P4 and P5 winners with identical source/engine/target/recovery/survival/scenario and complete 100-mob results. Require `T30 <= 1.01 × T300` in comparable seconds per mob. Proxy versus real-NPC, sequential versus simultaneous 2D, or different starting/continuing resources is not apples to apples.

### P7 — MythicSim reference, five independent tests (USER-REVISED 2026-10-28)

**The old P7 Decisions-challenger gate is replaced, not retained and not renamed P8.** P7 consists of the five required subgates P7.1, P7.2, P7.3, P7.4 and P7.5. A checkpoint has P7 PASS only if all five PASS with compatible source/engine and the *exact same saved reference encounter*. `dsim` can remain an optional diagnostic challenger but is no longer mandatory for P7.

**Reference identity and fidelity (applies to P7.1–P7.5).** Pin the *saved* MythicSim ranking report ID and source URL, character class/spec/level/race, full gear/enchant/consumables/buffs/debuffs, talents, priority/rotation and its conditions, native engine/ruleset/source revision, iteration/seed policy, encounter duration/variation, target stats and baseline DPS. Do not substitute the live tier-list card or another saved report whose DPS changed later. If critical settings of the specified saved report cannot be obtained, the gate is **BLOCKED: REFERENCE_CONFIGURATION_MISSING**, not approximated by guessed presets or an invented number. If the report and our pinned runtime have irreconcilable rulesets or combat assumptions, give an actionable mismatch rather than falsifying equality.

**Saved report extraction and evidence (applies especially to P7.1.1).** The saved report URL and the settings visibly rendered in its own interactive UI are authoritative reference evidence. Do **not** make a raw API/JSON payload, byte-exact original request, internal endpoint, or automatic scraping a new acceptance prerequisite when all relevant settings can instead be read reliably in that UI. Read and record all applicable fields *from that exact saved report*: gear/items/enchants, talent ranks, rotation/APL and conditions, buffs/debuffs, consumables and their use, encounter/duration/iterations and other exposed settings. Manual faithful transcription, screenshots, and an audited structured transcription of the visible UI are acceptable; keep the report ID/URL, field-level provenance, extracted values and any ambiguities, then validate the translated selected Rust/Go request against this inventory. Never silently substitute a different race-comparison or tier-list preset, infer unknown values from DPS, or claim exact provenance for guessed settings. A text-only fetch returning "Fetching the saved simulation" or omitting JavaScript-rendered fields is **a limitation of that reader**, not evidence the report lacks settings. Try an interactive browser/UI route or another faithful capture method before declaring information unavailable. Mark `BLOCKED: REFERENCE_CONFIGURATION_MISSING` only when a *material required setting actually cannot be determined after reasonable extraction attempts*; name the specific unknown fields and the attempted routes. Do not falsely claim settings have been extracted if the UI was not examined. This rule changes **source acquisition**, not the P7.1.2 native or P7.1.3 live acceptance standards; raw payload retrieval is optional supporting evidence.

**Production integration required (P7.1.3 and P7.2–P7.5; P7.1.2 is native diagnostic exception).** Every acceptance-scored production measurement runs OUR real `gsim` 2D world/controller interactively with one selected genuine pinned MythicSim **Rust (preferred) or Go** engine on one shared monotonic clock. gsim owns coordinates, facing/range, movement, CC and world effects; selected native engine owns combat/resource/cooldowns/buffs. World requests each boundary/ACK and native advances only to it; world state affects the next native decision. Commit a genuine world→native→world causal trace. Standalone `forever-engine sim` / `wowsimcli sim`, fixed coordinates without gsim, fake world or post-hoc replay FAIL/BLOCK live integration even at equal DPS.

**P7 DPS encounter world special case.** Model the saved MythicSim reference as a legal 2D scenario: a **level 63** stationary target that **does not attack the player** in the DPS benchmark, no adds, player begins at an optimal valid position for the chosen rotation (e.g. immediately in melee range or at the configured caster range), with **front/back explicitly selectable** and confirmed by the controller's coordinates and facing. No assumed closing travel is added when the reference has none. Use the report's actual encounter time distribution (the reference tier-list methodology defaults to about 120s ±15s) and all exact buffs, consumables, etc. If this world-side non-attacking target or front/back orientation does not causally determine selected Rust/Go engine behavior via the live handshake, FAIL. P7's **DPS** objective does not replace P4–P6's 100 consecutive-mob **seconds/mob** objective.

**P7.1 — Fixed reference reproduction; native baseline followed by engine-integration test.** Execute P7.1.1 → P7.1.2 → P7.1.3 in order. Gear, talents, rotation/APL and the saved encounter are fixed across both executions. All three steps are mandatory for P7.1 PASS; the native run does **not** substitute for the live 2D integration test.

**P7.1.1 — Saved reference configuration.** Obtain and pin the **exact saved** MythicSim report configuration, including through its **visible interactive Settings/UI** (raw JSON is optional): report ID/URL, class/spec/level/race, full gear and enchants, talents, priority/rotation/APL and conditions, buffs, debuffs, consumables and their usage, encounter target and orientation, duration/distribution, iteration and RNG policy, source/ruleset/database revision insofar as determinable, and reference DPS. Maintain a field-by-field reference inventory and record the original visible source and any uncertainties; verify that the selected Rust/Go request faithfully expresses the inventory. Do not substitute a reconstructed preset from another report. If a *material required setting truly remains unknown* after trying to inspect the saved UI, mark **BLOCKED: REFERENCE_CONFIGURATION_MISSING** and specify the missing field(s) and extraction limitation. The absence of raw JSON **alone** must never block this gate.

**P7.1.2 — Native MythicSim Rust/Go reproduction (mandatory pre-integration diagnostic).** Execute exactly the P7.1.1 saved configuration (gear/enchants/talents/APL/buffs/debuffs/consumes/encounter) in **one real pinned Rust or Go native engine**, without gsim-2D. Rust is preferred, Go equally valid. Match source/ruleset/database, seed/iteration and stochastic scoring. No optimization or invented substitutions. Require native DPS >= the pinned saved reference with compatible statistical evaluation; publish full request/output, build/config hashes and combat metrics. Native success alone is not a new production P7.1 PASS.

**P7.1.3 — Live gsim-2D ↔ selected MythicSim Rust/Go reproduction (production acceptance).** Execute the same pinned config through real interactive gsim-2D↔selected native engine, ideally the same backend as P7.1.2. Demand DPS >= saved reference under compatible stochastic evaluation and genuine causal world→native→world trace. If backend changes, rerun native comparison on the selected backend. No standalone, fake or post-hoc PASS.

**P7.2–P7.4 external reference tolerance (OWNER-APPROVED 2026-10-29).** For the **independently discovered** winners of **P7.2, P7.3 and P7.4 only**, the minimum reference-relative DPS is `DPS_winner >= 0.99 * DPS_external_reference` on the same pinned saved encounter, ruleset, native engine and scoring policy. The 1% margin changes **only these three gates' external DPS floor**; all 300-second independent cold searches, legality, production live 2D causality and complete measured evidence remain in force. **P7.1 remains exact reference reproduction** (`DPS >= DPS_external_reference`). **P7.5 retains its full external reference floor and 99%-of-strongest-accepted-compatible-prior floor, but the P7.5 PASS statistic is the frozen stochastic holdout mean (v2.10), not the former 95% confidence lower bound.** This permission does not waive unproven runtime integration or endorse an over-budget run.

**P7.2 — Rotation discovery.** Fix the reference's **gear and talents**. Run an **independent cold 300-second** optimization of source-legal rotation/policy; do not seed the free rotation dimension with the saved reference rotation. Each paid candidate executes through the same coupled 2D+native reference scenario. Require the discovered legal executable rotation to achieve **DPS >= 0.99 × the pinned MythicSim reference DPS** under the same encounter and scoring policy. Publish winning policy, genuinely paid candidate count, full measurement and causal trace.

**P7.3 — Talent discovery.** Fix the reference's **gear and rotation**. Run an **independent cold 300-second** optimization of source-legal talent ranks/allocations, respecting all prerequisites/point budgets and interaction with the fixed rotation. Do not seed the free talent dimension with the reference allocation. Require **DPS >= 0.99 × the pinned MythicSim reference DPS**, measured by the same 2D+native production pipeline. A fixed rotation referring to a talent-only unavailable action must be handled legally, not magically unlocked.

**P7.4 — Gear discovery.** Fix the reference's **talents and rotation**. Run an **independent cold 300-second** optimization of legal equipped gear (including items/enchants constrained by the reference rules); do not seed the free gear dimension with the reference loadout. Require **DPS >= 0.99 × the pinned MythicSim reference DPS** measured by the same 2D+native pipeline. Report item IDs, whole loadout, paid candidate count and DPS evidence. (Original four-way design: baseline + three single-free-variable searches; P7.5 now adds a separate joint search.)

**P7.5 — Joint gear × talents × rotation discovery (USER-APPROVED 2026-10-28).** Run an **independent cold 300-second wall-clock** whole-build search (gear, talent allocations and rotation/policy all free) using the pinned saved reference class/spec/level/race, gear legality, encounter, buffs/debuffs/consumes and source/ruleset through a **genuinely live gsim-2D ↔ selected MythicSim Rust/Go** production integration. Never seed saved reference config or any P7.1–P7.4 winning build. Candidates must be legal, fully specified and actually executed; report paid unique count, wall time, winner gear IDs/enchants, talents, APL, engine/config hashes and world↔native trace.

**Mandatory P7.5 non-inferiority acceptance (USER-REVISED 2026-10-30; issue #10).** The independently frozen P7.5 stochastic holdout **mean DPS** must reach **both** (a) the full external saved MythicSim reference mean DPS and (b) at least **99% of the strongest *accepted and compatible* P7.1–P7.4 independently measured stochastic mean DPS**, with the SAME pinned reference encounter, source/ruleset, native engine, target, duration distribution, buffs/debuffs, consumables and scoring policy. Do not select the comparator from an unaccepted diagnostic result or mix incompatible runs:

`mean_DPS_P7.5_frozen_holdout >= max(DPS_external_reference, 0.99 * max(mean_DPS_accepted_compatible_P7.1, ..., mean_DPS_accepted_compatible_P7.4))`.

Require an independently frozen stochastic holdout of **at least 1,000 fights** with the selected genuine native Rust/Go engine's original **stochastic** RNG, separate from balanced-RNG search evaluation. **PASS/FAIL uses the frozen holdout *arithmetic mean DPS* against both floors — no one-sided 95% confidence-bound or p95 lower-bound PASS criterion.** Report standard deviation, standard error and confidence intervals if helpful for diagnostics, but they do **not** impose additional pass thresholds. Before establishing the strongest accepted-compatible prior, verify the accepted gate decision, frozen stochastic mean, fully source-legal gear/talents/APL and matching pinned engine/encounter/duration/buffs/consumes/RNG/scoring configuration; where prior results are incompatible, rerun the accepted prior winner with matched conditions and report the new provenance. **An unvalidated native-only candidate or unresolved legality/compatibility (for example PR #23's 797.362 DPS P7.4 result) cannot automatically become the P7.5 comparator; BLOCK comparator selection if unresolved.** Never change the winner or comparator after seeing P7.5 holdout. Rediscovering a prior winner independently is legal; seeding a cold search with a reference/prior winner is not. The 300-second cold-search budget and real live 2D↔native source/legal/causal requirements are unchanged. A below-floor holdout mean is FAIL; missing comparable accepted priors or missing required evidence is BLOCKED, never inferred PASS.

**Retrospective acceptance:** Previously measured, genuinely frozen stochastic winners MAY be re-evaluated under v2.10's **mean-DPS** criterion without erasing their historical PASS/FAIL verdicts. In the historic WF613 Feral example, published P7.5 mean 848.764 DPS and reported P7.4 mean 853.931 DPS would imply a prior-relative floor of approximately 845.392 DPS, while the saved external floor was 811.024 DPS. **These numbers are a conditional illustration, not an automatically validated comparison**: the strongest prior must be independently accepted, source-legal, and measured on compatible settings; verify raw holdout, provenance and exact accepted comparison set first. Its previous one-sided confidence-limit calculations are historical diagnostics, **no longer a PASS criterion**. Do not rescue an incomplete WF615 run or relax P7.1–P7.4 as a side effect.

**Pass reporting.** Present one shared saved reference ID/config hash and a selected genuinely coupled MythicSim Rust or Go runtime/version. Report all P7 gates with honest native and live-2D evidence; a standalone parity result does not establish live integration. Preserve owner-specific accepted historical Balance P7.1 Rust evidence without fabricating Go/2D tests. Never splice incompatible backends, scenarios or scores.

## 4. Gate-level RED → GREEN → REFACTOR

Every genuinely new or repaired gate uses **RED** (same real acceptance predicate fails, with evidence) → **GREEN** (same predicate actually passes) → **REFACTOR** (audit whether a class/spell/talent/item-specific fix belongs in generic IR/executor/optimizer/data instead). Rerun the SAME predicate after refactoring plus relevant cross-class/cross-level regression; invalidate dependent downstream evidence when executable behavior materially changes. Test count, metadata completeness and synthetic fixture greens **never** substitute for the actual gate predicate. **For P2, a correctly implemented, genuinely behavior-tested talent is PASS; never insert a separate "semantic-proof" or provenance-bridge phase between GREEN and the next gate.** Do not re-run unmodified expensive proofs without a dependency change if exact evidence/source/runtime hashes remain current; cache valid certificates and demonstrate freshness.

## 5. Efficient W execution and source discipline

- Before work AND before publish, inspect newest Library baseline, especially parallel-agent overlays and handovers; rebase or merge, never overwrite sibling changes. One authoritative linear parent per released overlay.
- Choose the **largest material accepted-checkpoint/critical-path gain within one execution window**; avoid version inflation for bookkeeping, new wrappers, test counts, isolated micro-features or speculative total-source scraping that doesn't unblock a concrete gate.
- Fast, focused, exact evidence tests; isolate genuinely long 30s/300s/100-mob acceptance from short unit regressions. Record real wall times, candidate counts, source revisions, numeric scores and blockers. Interrupted/resumed runs must account for paid work honestly.
- Generic behavior in selected production engine(s), Forever-specific facts in pinned source-versioned canonical DB. Do not silently invent constants or omit legal abilities; acknowledge specific coverage gaps separately from the deliberately minimal P3 scorer smoke test. **Source provenance alone is not a separate talent acceptance gate: once a sourced/available mechanic is implemented and behavior-tested, proceed.** Only investigate source data further when necessary to implement an actually missing behavior, fix a failing test, or resolve a demonstrated contradiction that affects execution.
- Every W deliver a real code/evidence delta, versioned ZIP, validation and handover when a useful change is achieved; if blocked, say so without fake publication. Preserve clean baseline. The implementation plan may be changed by W to improve speed and token economy; PROCESS and OVERALL PLAN may not.

## 6. Governance enforcement and change control

Every W/handover must name the approved PROCESS and OVERALL PLAN version+SHA256, and verify their bytes have not changed. Agent-drafted changes are submitted as separate `*_PROPOSED` documents with a concise before/after diff and the user's explicit approval requested before promotion. Do not amend an approved version in place. An explicit user change to P3/P4 or another rule triggers creation of a NEW frozen PROCESS version; an explicit change to the end goal or DONE DONE triggers a NEW frozen OVERALL PLAN version. Milestone-level experiments, bug fixes and estimates do NOT trigger sacred-document changes.


## Migration and removal policy (USER-REVISED 2026-10-26)

1. Implement/test **Druid L60** with the existing canonical gate CLI; report gsim plus selected `msim-rust` or `msim-go`/hybrid evidence separately. Prefer Rust when actually integrated and pinned; no inference from source code or build green.
2. Grow to all nine classes at **L60 and L40** on the real selected Rust/Go + gsim-2D production path, covering class/profile mechanics and preserving continuous resource/CC/cooldowns/recovery. Inventory or compilation alone is insufficient.
3. **Do not remove gsim or its working tests** while selected Rust/Go/hybrid is incomplete. Keep any valid gsim PASS, and retire older paths only after demonstrated cross-class L40/L60 integration with L20/L30 preserved and regression tests. No new gate or reduced 148 scope.
4. `dsim` stays available as an optional historical diagnostic challenger even if gsim is eventually retired; it is not P7 evidence. No class-specific winner presets, silent ability exclusions or new hidden gate is authorized.
5. No separate "wrapper green" counter or backend-migration checkpoint is added to the 148 scoreboard; report any migration progress as diagnostic until real P1–P6 and P7.1–P7.5 acceptance.

## Evidence/source discipline inherited from approved PROCESS v2.2

## Mandatory rule: no imaginary server-measurement or semantic-certification gates

1. Use the best available game data and known mechanics, including established Classic mechanics as defaults **unless concrete evidence indicates Forever differs**. Keep the chosen assumption and source visible where it materially affects a result.
2. Implement the mechanic via canonical sourced data and the selected executable gsim/msim-rust/msim-go/hybrid route, test actual observable behavior, then advance to the next acceptance gate. (The new backend-neutral rule supersedes the gsim-only wording in v2.2.)
3. Do **not** demand a Forever live-server measurement, internal-server access, build-to-build semantic parity proof, source-version bridge, or standalone semantic-verification round merely to accept an otherwise working implementation. No such extra gate exists.
4. Investigate uncertainty only when there is an **actionable** missing implementation, failing behavior test, contradictory data, or a demonstrated material effect on outcome/comparability. Describe the exact defect and fix it; don't block progress on speculative provenance concerns.
5. Synthetic edge-case inputs (for example 60% spell hit) are legitimate unit-test fixtures but **must be labeled synthetic**, never described as measured Forever mechanics. Distinguish test fixture, Classic-derived default, source data, and real 100-mob simulation.
6. Do not invent source values or silently override actual Forever-specific data. Where Forever-specific evidence contradicts a Classic default, use the better supported rule and rerun affected tests.
7. P2 remains binary: suitable implementation plus meaningful passing behavioral tests = PASS; otherwise FAIL with a concrete defect. No `PARTIAL_SEMANTICS` or `SEMANTICS_UNVERIFIED` acceptance status.
8. This does not waive the actual P1–P6 and P7.1–P7.5 criteria, real 30/300 leveling searches, independent 100-mob measurements, or the five externally pinned P7 checks. It removes **only fabricated proof requirements**.


## Execution instruction

At each W, prioritize code, behavior tests and measured full-simulation progress. Do not spend a W on evidence archaeology unless it resolves a concrete failing behavior or materially incorrect result. Record real PASS/FAIL and do not claim an acceptance or publication that has not occurred.

## v2.3 approval/change record

- User explicitly requested this PROCESS gate update 2026-10-26. Previous APPROVED documents are preserved byte-for-byte; unapproved PROCESS v3 / OVERALL v6 drafts are not adopted.
- Only this new v2.3 contract defines the accepted backend-neutral path once published; keep pinned source/build/proof hashes in every release.
- No change to OVERALL PLAN v5; it names a generic source-driven optimizer with observable, reproducible 148-checkpoint capability, not a required gsim implementation language.

## v2.4 approval/change record

- User directed the PROCESS rewrite on 2026-10-27 and explicitly chose P7.1–P7.4 in place of the Decisions P7, with P7.1 required to exercise *our interactive 2D+native integration*, not an external Go engine standalone call.
- v2.3 bytes and P1–P6 behavioral requirements are preserved in the historical approved document. No P8 added, no reduction to 148 checkpoints.
- OVERALL PLAN v5 still literally names Decisions as held-out P7; a proposed v6 is supplied separately. Until approved, make the contradiction visible in handover rather than silently modifying OVERALL PLAN v5.

## v2.5 approval/change record

- On **2026-10-28**, user explicitly instructed: **add P7.5**, and confirmed **P7.5 must be at least as good as every P7.1–P7.4 winner**. Those two requirements constitute explicit authorization for this new PROCESS version.
- P7.5 is a **required fifth subgate within P7**, not P8 or an additional checkpoint. The scoreboard stays at **148** checkpoints; no checkpoint is complete without P7.5 PASS.
- The original approved v2.4 source remains immutable. P1–P6 and P7.1–P7.4 criteria are not relaxed or retroactively relabeled.
- OVERALL PLAN v5 remains immutable; its mismatch is tracked in a separate *proposed* v7, not silently approved.

## v2.6 approval/change record

- On 2026-10-29 user explicitly approved the 1% P7.5 non-inferiority tolerance while retaining the external MythicSim reference as a hard floor.
- P7.1–P7.4 are unchanged; 148 checkpoint accounting remains unchanged. P7.5 still requires independently cold 300s discovery and at least 1,000 stochastic holdout fights, live 2D↔Go integration and statistically defensible comparison.
- Historical outcomes remain attached to their original process version; revised acceptance must be labeled v2.6.


## v2.7 approval/change record

- On 2026-10-29 user explicitly approved adding **P7.1.2**: run the exact saved reference first in native MythicSim Go **without** gsim integration, with all reference gear, enchants, talents, rotation/APL, buffs, debuffs, consumables and encounter settings unchanged.
- P7.1 now comprises P7.1.1 reference configuration, P7.1.2 native Go reproduction and P7.1.3 live gsim-2D↔Go reproduction, in that order. All three are required; native success does not waive the live integration requirement.
- The blanket P7 live-integration wording has an explicit **P7.1.2-only exception** so the process is internally consistent. P7.2–P7.5, P1–P6, P7.5's 1% criterion and 148-checkpoint accounting are unchanged.
- v2.6 remains intact as the historical approved version.


## v2.8 approval/change record

- On 2026-10-29 the user explicitly instructed recording the lesson from the Balance 728-DPS reference extraction in the PROCESS: the settings shown behind the **exact saved MythicSim reference link** should be used; extraction failures with a text-only/JavaScript-incomplete reader are not proof that the data are absent.
- The saved report UI/Settings is accepted as an authoritative source. A faithful field-by-field transcription from it suffices; raw report JSON/API bytes are optional diagnostics, **not** a hidden prerequisite. Do not use another report's race comparison preset as a substitute.
- Report `BLOCKED: REFERENCE_CONFIGURATION_MISSING` only for genuinely unresolved material fields; disclose the precise fields and attempted UI extraction method. Native P7.1.2 and interactive P7.1.3 requirements remain mandatory and unchanged.
- All previously approved checkpoints and thresholds stay unchanged. v2.7 is preserved as a separate immutable historical file.

## v2.9 approval/change record — selectable MythicSim combat engine

- 2026-10-29: explicit user approval to prefer **Rust**, while accepting genuine **Rust or Go** for native and live-integrated combat on compatible pinned rulesets.
- P7.5 independent frozen stochastic holdout uses the selected engine's original stochastic RNG (not balanced-RNG optimization surrogate). No cross-engine score splicing.
- Historical Balance L60 P7.1 owner-accepted pinned Rust replay remains CLOSED with Go/live-2D gaps disclosed. This individual acceptance is not a general waiver of production integration.
- Historical v2.9 rule (superseded by v2.10): P7.5 once required a one-sided 95% confidence lower-bound PASS. Its >=1,000-fight frozen holdout, 100%-external and 99%-best-accepted-compatible-prior floors, and <=300s cold search remain in force. OVERALL_PLAN v5 is unchanged; Git holds history.
- Earlier approval records keep their historical Go wording, but active normative rules above supersede the backend-specific restriction.


**2026-10-29 historical gate-floor change (P7.2–P7.4):** P7.2–P7.4 use **99% of the same saved external reference** as their minimum DPS threshold. P7.1 and the P7.5 external-reference **100% floor remain untouched**. At this earlier point P7.5 also required a one-sided 95% holdout bound; **that historical requirement is explicitly superseded by v2.10**. Git records the full edit history.


## v2.10 approval/change record — issue #10 P7.5 frozen mean

- **2026-10-30 explicit owner correction:** remove the one-sided 95% confidence-bound PASS criterion. **Only the independently frozen stochastic holdout's mean DPS** is compared against the full saved external reference and 99% of the strongest *accepted, compatible* P7.1–P7.4 stochastic mean. Uncertainty is reportable, not an extra pass bar.
- A prior winner's acceptance, legal equipment/enchants and same pinned engine/encounter/duration/buffs/consumes/RNG/scoring must be shown; incompatible historical winners require a matched rerun. Unaccepted P7.4 797.362 DPS in PR #23 is **not** automatically a valid prior floor. No apples-to-oranges comparison.
- **Unchanged:** >=1,000 independent stochastic holdout fights; independent cold search <=300 seconds; legality; genuine live gsim-2D↔selected Rust/Go causality; P7.1 exact reference; P7.2–P7.4 99%-external; all 148 checkpoint definitions. 
- The active rules above supersede historical v2.5–v2.9 confidence statements; those older passages are preserved as historical version records, not operative acceptance conditions. [Issue #10](https://github.com/dosibjrn/mage-level-sim/issues/10) records the exact owner instruction.
