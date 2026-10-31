# Backlog

## Refactor parity freeze

During the v0.10 ruleset/class refactor, existing Classic Era Mage behavior is a compatibility contract. Do **not** opportunistically fix pre-existing Classic mechanics while the refactor is in progress. Record them here, reproduce them if useful, and address them only after the refactor has a frozen parity baseline.

### Architecture follow-up after parity freeze

- Move the canonical Classic Mage implementation from `src/classic_mage_leveling_optimizer_v10.py` behind `src/rulesets/classic/classes/mage/` only after providing a migration path for persisted pickle module identities and simulator/cache fingerprints. Until then the old module remains canonical and the ruleset package is an ownership facade.
- Split very large class engines further (`talents.py`, `spells.py`, `mechanics.py`, `profile.py`) only where the split can be behavior-neutral and covered by parity tests. The package boundary is the stable API; file-level decomposition is secondary.

### Forever performance follow-up

- Forever Mage 11→30 smooth analytic search completes all independent level pools, but continuity repair is substantially slower than the Classic-sized tree in the current experimental build. Profile/bound the repair scoring after v0.10 architecture parity is frozen; do not weaken the exact Classic path logic just to make the experimental smoke faster.

### Classic mechanics bugs / suspicious behavior

Add newly discovered pre-existing Classic issues here instead of fixing them during the refactor. Each entry should include a minimal reproduction and whether it changes optimizer ranking or only diagnostics.

### Forever beta data follow-up

- Mage modeled core spell ranks are now normalized to the canonical 1.60.1.69893 fixture (`tests/fixtures/forever/1.60.1.69893/mage_core_spells.json`). Keep future beta updates build-scoped: add a new fixture directory instead of silently editing provenance.
- Add the same canonical raw-fixture treatment for the full Mage talent tree and then for Paladin/Druid spell/talent data. Current Pala/Druid profile metadata is build-scoped, but their first-cut approximate mechanics still embed some action coefficients directly in code.
- When a newer Forever client build supersedes 69893, compare fixtures first and separate pure data drift from mechanics changes in release notes.

### Forever Paladin pack-policy follow-up (v0.10.2)

- Keep Paladin `gear.py` as a **normal attainable gear curve**, not an inventory/loot optimizer. Calibrate weapon/armor/stat anchors from ordinary crafted/dungeon/world-drop examples when useful, and let per-level stat weights guide a small number of explicit stat-mix revisions. Do not add item-combination dimensions unless the user changes scope.
- Verify Seal of Fury absorb shield stacking/replacement semantics against direct game observation. v0.10.4 now uses a conservative single-shield replacement proxy and only pays Improved Seal of Fury mana on fully broken shields; stacking/refresh behavior remains provisional.
- Shield Specialization now uses the verified 3-second ICD with an expected-renewal proc-rate model. Later event-sim work should replay the exact ICD timeline rather than expected rate.
- **v0.10.5 completed:** Fast no longer uses fractional in-combat healing; it uses whole heal casts plus explicit emergency windows. A future event backend still needs exact swing/GCD/cooldown replay before MC.
- Add exact Seal of Righteousness speed formula and canonical Seal of Command proc/rank fixture. v0.10.2 now models SoC using the verified 70% weapon-damage tooltip plus an explicit Classic 7-PPM approximation; preserve that approximation label until Forever proc semantics are directly verified.
- v0.10.4 adds level-scoped +1/+2 ordinary-world melee fixtures with fast/light, normal and slow/heavy swing families while preserving mean raw DPS. Replace the provisional Classic-like raw-DPS curve when trustworthy Forever NPC stats become available.
- MC remains disabled for Paladin until a deterministic action/event backend can replay the same priority policy and survival controller.

- **v0.10.5 completed at Fast fidelity:** HP and mana now both have repeatable pack/recovery state, explicit start/end/peak mana and exact recovery deficit. Event-by-event mana timing remains future work.

### Forever Paladin Judgement / reporting follow-up (v0.10.4)

- Forever Judgement now preserves the active Seal; do not reintroduce automatic reseal cost after each Judgement. Sanctified Judgement is modeled as an expected refund against the Seal cost.
- Keep `talent_family` separate from `combat_profile`: a Protection-heavy talent allocation may rationally use 2H / Righteousness or other non-shield play at a given level. The optimizer must not encode `Prot == shield` as a rule.
- Current 10→30 smooth results changed materially after fixing Judgement seal preservation; do not compare v0.10.3 crossover levels to v0.10.4 as if the objective were unchanged.

### Forever Paladin search-performance follow-up (v0.10.5 -> v0.10.6)

- **v0.10.6 first pass completed:** profile-guided static-context sharing + proof-safe mana-plan upper-bound pruning preserve complete representative score JSON while reducing the lvl-20 beam diagnostic from ~13.37 s to ~8.36 s in the checkpoint environment.
- Broad 10->30 Paladin search is still heavier than desired. Future optimization must remain semantics-preserving; profile first and prefer cache/equivalence/dominance work over narrowing the product objective.
- Keep `--no-stat-weights` available for broad diagnostic smokes; default per-level decision reports should continue to expose stat weights.

### Forever Paladin deterministic event replay follow-up (v0.10.6 -> v0.10.7)

- **v0.10.7 completed:** deterministic event replay now includes whole heal casts, HoJ single-target stun state, BoP / Divine Protection physical-immunity + Forbearance state, Shield Specialization deterministic block-credit + hard 3 s ICD, and one-replaceable Seal of Fury absorb/break mana state.
- **v0.10.7 completed:** visible Fast candidates can be replayed through `paladin.validation_report`, producing a hybrid event-adjusted cycle (event combat/end resources + explicit smooth OOC recovery) while remaining diagnostic-only.
- **v0.10.8 completed:** Fast HoJ emergency healing now suppresses one expected attacker rather than the whole pack, utility GCD time consumes the window, and Improved HoJ / Guardian's Favor / Sacred Duty feed repeat cooldown floors. The 10→30 before/after sweep changed no Fast top-1 decision and found no visible top-5 panic-dependent row.
- Event healing uses the smooth expected pushback-adjusted cast duration rather than individual pushback events. Exact pushback belongs in stochastic/event hardening later.
- Shield Specialization event replay is still deterministic expected-block credit, not RNG blocks/procs. Seal of Fury shield generation remains expected-value on own hit and replacement semantics remain provisional until combat-log evidence resolves stacking/refresh behavior.
- A newly noticed SoC detail: Judgement has extra damage against stunned/incapacitated targets in current Forever data; neither Fast nor event replay applies that stun bonus yet. Add as a build-scoped mechanic before using HoJ offensively in scorer authority.
- **v0.10.8 completed:** 10→30 smooth-vs-event finalist validation now preserves a deeper hidden Paladin finalist pool (target 20) and classifies talent-only versus material playstyle changes. Only lvl15 changed gear/pull/profile-level playstyle in the checkpoint sweep (2H/1 mob -> shield/2 mobs).
- Next: publish event-finalist decisions as a separate first-class per-level output before considering scorer promotion. Keep Fast no-respec path distinct and keep MC disabled until the deterministic contract is stable.

### Forever Druid incoming-damage Rage closure (v0.11.48.113)

- **Completed:** Blizzard states Forever keeps the original Rage-from-damage-taken formula but ignores the player's real Armor and absorbs, evaluating the formula as if Armor always reduced incoming damage by 50%.
- Runtime now feeds the Rage formula `pre-armor incoming × 0.50 × successful-hit fraction`; actual Armor still reduces survival/recovery damage.
- Avoidance remains outside the fixed-Armor substitution because a missed/dodged attack deals no damage.
- First-party source: Blizzard *World of Warcraft: Forever Class Deep Dives — Priest and Warrior* (`https://worldofwarcraft.blizzard.com/en-us/news/24301514`). Original conversion coefficients remain pinned to the Classic RewardRage implementation provenance.

### Cross-class comparison follow-up (v0.10.5)

- `src.v2.class_comparison` deliberately exposes raw throughput plus fidelity rather than producing a confidence-adjusted winner. Keep that property until Mage/Paladin/Druid backends reach comparable objectives.
- Druid must gain multi-pull survival/recovery + normal gear/stat guidance before its raw throughput should be compared strongly with Paladin.

### Player-facing decision tooling follow-up (v0.11.1)

- **v0.11.0 completed:** bounded per-level frontier, milestone endpoint paths,
  preserved-route regret, honest dual-spec status, route stat/rotation matrix,
  `/decisions`, and a general read-only constraint/regret API.
- **v0.11.1 completed:** route-transition timeline, per-level named-route regret
  curves, batched/cached multi-route stat matrices and stat trend lines in
  `/decisions`.
- **v0.11.1 completed:** configurable-unlock joint dual-spec solver.  It chooses
  between two preserved paths independently after unlock and publishes compact
  phases. v0.11.4 makes the verified cap confidence metadata rather than a hard
  gate: L40/L60 results may be published provisionally above the cap, but must
  remain visibly non-authoritative until the underlying beta data is verified.
- **v0.11.1 completed:** custom constraints can be composed in `/decisions`.
  Missing corridors remain non-authoritative and return a copyable wider
  frontier command plus repeat-query command; HTTP never launches either.
- Future: make the rerun itself constraint-aware (corridor retention), rather
  than relying on a wider generic beam, while retaining an explicit opt-in.

### Forever item calibration follow-up (v0.11.4)

- `data/forever/item_samples_trusted.csv` seeds the calibration set with only
  screenshots that show both required level and displayed stats. Keep unknown
  fields unknown; do not convert missing random-suffix tooltip stats into zero.
- Current samples are concentrated around low-level mail/weapon examples. Add
  the user's L10/L15/L20 AH samples before fitting new normal gear curves.
- Do not auto-generate every Paladin/Druid route stat matrix inside the broad
  experimental search yet: the Paladin stat probes make that post-pass expensive.
  Keep matrix generation explicit/cached until the probe cost is reduced.

## Post-v0.11.12 spell-modifier follow-ups
- Audit Druid spell/ability coefficients rank-by-rank against current Forever pages.
- Audit Paladin spell/ability coefficients rank-by-rank against current Forever pages.
- Resolve Ice Lance SP modifier only from a trusted Forever source; current Wowhead page hides it behind server-side dummy effects.
- Separate mechanics pass: current Fireball/Pyroblast Forever pages flag attached periodic damage as crit-capable; model and regression-test if verified in runtime behavior.


### Druid Bear multi-pull follow-up (v0.11.18)

- **v0.11.18 completed:** Bear 1–3 pack search, shared exposure geometry, verified Swipe target cap/ranks, verified Maul cost, Bear Mangle rank flats, shared recovery.
- Resolve Swipe hidden weapon/server-side scaling from a trusted Forever source.
- Add incoming-damage rage only after verifying the Forever rage formula.
- **DONE through v0.11.48.12:** Bear mitigation path includes Thick Hide, Natural Reaction, and generic +Defense miss+dodge avoidance. Forever-specific incoming-damage Rage conversion remains the unresolved survivability/resource coupling.
- Audit Cat Swipe separately; do not copy Bear Swipe semantics.

## v0.11.26 follow-ups
- Add analytical Stamina / armor / defense / healing derivatives for Paladin so per-slot role-peer rerolls can value defensive tradeoffs directly.
- Build a weapon-specific budget exchange model before placing weapon DPS on the same equal-budget axis as primary stats.
- Reuse the shared equal-budget projector for Druid once the Druid analytical stat-gradient backend exists.
- Keep expanding real quest/dungeon/world-drop anchors at levels 10-60; continuous fields remain the interpolation/extrapolation layer between audited samples.

### M47 throughput notes — retained facts, not active validation queue

- **Paladin weapon throughput may be real, not a nerf target.** White autoattacks run independently of active GCDs. A strong attainable 2H plus Seal/Judgement/Holy Strike/Consecration can legitimately make Ret a very strong PvE leveler. Do not force class parity by tuning mechanics.
- **Mage HP-aware wand finishing is implemented and regression-covered at L20/L40/L60.** It remains a policy decision rather than an always-wand rule.
- **Mage recovery uses strict best usable water by default.** Self-conjured-only water is a sensitivity mode. Mana Gems and Evocation are already part of the continuation/recovery path.
- Do not create new per-level adversarial campaigns. Concrete missing gameplay work lives in `FEATURE_GAPS.md`; default validation is the bounded `run-validation-fast` command.

## Deferred gameplay/fidelity TODO while platform track is active (v0.11.48)

These remain real model gaps; they are deliberately parked rather than lost while the Optimizer Service/platform track is implemented.

- **Mage:** finish lower-severity fidelity follow-ups such as periodic-crit side-effect interactions (Ignite / Hot Streak / Master of Elements only where current Forever evidence supports them) and any remaining source-backed control/root edge cases. Ice Lance route authority is no longer in this TODO: v0.11.47.24 fixed the runner -> endpoint artifact -> listener authority chain.
- **Druid:** replace/verify the current target-server incoming-damage -> Rage proxy when authoritative Forever evidence exists; add a generic Defense -> avoidance contribution before treating Bear survivability as fully comparable across classes.
- **Paladin v0.11.48.114 DONE:** weapon DPS is compared to primary stats only inside a dedicated real-weapon peer budget domain, separated by 1H/2H selected gear style. Existing defensive derivatives remain unchanged.
- **Cross-class gear/fidelity:** expand real named-item anchors through the leveling range and only strengthen raw Mage/Paladin/Druid throughput comparisons when combat/gear/pull contracts are genuinely comparable.

Platform work may proceed without closing these rows. Return to them after the durable service/control-plane path is usable or if one becomes a blocker for service integration testing.


## Optimizer Service platform TODO after v0.11.48.4

- **P2b DONE v0.11.48.2:** shared executor contract for v2 smooth/fast and MC/master optimizer with explicit work-unit/stop semantics.
- **P3a DONE v0.11.48.3:** durable checkpoint manifest + compatibility classifier (`resume` / `seed_only` / `incompatible`) + SQLite artifact metadata.
- **P3b DONE v0.11.48.4:** strict compatible checkpoint selection + verified staging into fresh immutable attempts; seed-only is excluded from numeric resume. External attempt-root checkpoint paths are supported.
- **P3c DONE v0.11.48.5:** atomic canonical publication pointer over immutable attempt state, last-good preservation, and overlay resolution so class-local publishes do not erase prior class artifacts.
- **P4a DONE v0.11.48.6:** compute-free HTTP control/read API + bounded SSE event stream over durable service state.
- **P4b DONE v0.11.48.7:** shared HTTP client; CLI is HTTP-by-default and listener service status/publication reads use the API; direct/local recovery remains explicit via `--direct`.
- **P4c:** listener job queue/progress/control UI on the same API; no HTTP-triggered optimization.
- **P5 DONE v0.11.48.11:** bounded simultaneous jobs + resource admission + two-job writer-isolation proof; publication commit serialized.


## Optimizer service platform follow-up (v0.11.48.6)

- P4a DONE: HTTP control/read API and replayable SSE event stream.
- P4b DONE v0.11.48.7: shared HTTP client + HTTP-by-default CLI + listener service status/publication reads; direct-store maintenance remains explicit.
- P5 DONE v0.11.48.11: bounded worker concurrency/resource admission; single-worker remains the default unless configured higher.

## Optimizer service platform follow-up (v0.11.48.8)

- P4c DONE: listener queue/progress/control workbench on the shared HTTP API; enqueue, pause/resume/cancel, priority ordering, durable state/latest-event display, and no browser-side optimizer execution.
- P5 DONE v0.11.48.11: two-job disjoint-root isolation and serialized publication are regression-covered.

## Hunter onboarding follow-up (v0.11.48.58)

- v0.11.48.61 removes the Hunter proof-only presentation and switches Hunter gear/ranged weapons to the user-supplied canonical SQLite catalogue. Verified mechanics coverage remains explicitly capped at L20 until later levels are implemented.
- **DONE v0.11.48.61:** canonical SQLite Hunter named items and ranged weapons replace the temporary level curve.
- Add ammo/quiver haste and ranged weapon normalization only from pinned Forever evidence.
- **PARTIAL v0.11.48.60:** family damage/health/armor modifiers, engage uptime, expected attrition, Endurance Training and Improved Revive Pet are live scorer inputs. Remaining: individual-pet attack-speed effects, focus/skill ranks/active family abilities, and stronger survival calibration.
- Add deadzone/melee-weave, traps and Multi-Shot pack search as explicit policy dimensions rather than hand-tuned bonuses.
- Extend L21-L60 only after the L10-L20 source/mechanics contract is stable.
- **DONE v0.11.48.62:** Druid Feral talent path publishes separately as `Feral · Cat` and `Feral · Bear`; both reuse the Feral talent constraint and force distinct combat-profile rescoring, without inventing talent specs.

## Architecture documentation refresh (v0.11.48.74.1)
- [x] Rewrite `ARCHITECTURE_AND_ALGORITHM.md` so the current `ClassModel -> search_level -> LevelFrontier -> solve_routes -> DecisionResult -> publication` contract is the entry point rather than historical Mage FAST/MC orchestration.
- [x] Document the honest migration boundary: Mage is an explicit plugin but still bundles mature structural/policy/gear internals; Hunter/Druid/Paladin/Warrior remain thinner compatibility adapters.
- [x] Make shared timing/recovery, Forever build identity, service/control-plane separation, and architecture invariants explicit.
- [x] Refresh `START_HERE.md` to point at the current architecture and `.74` handover.

## Platform refactor after v0.11.48.65
- DONE v0.11.48.65: introduce `ClassModel` / `SearchContext` / canonical `Evaluation` and make route DP consume opaque class semantics through the model instead of importing `eng`.
- NEXT: migrate per-level scorer outputs to canonical `Evaluation`, starting with shared timing semantics (`kill_s`, `recovery_s`, `travel_s`) so class comparison is apples-to-apples.
- NEXT: move fixed-point/search orchestration behind one generic coordinator; class models provide candidate generation, gear/policy optimization, evaluate, and stat weights.
- NEXT: route/publication authority consumes the same canonical `LevelFrontier`/route result so endpoint rows cannot disappear independently of DP state.
- NEXT: wrap Mage mature search behind `MageClassModel` and remove mature-vs-experimental orchestration split after parity/intentional-delta checks.

- [x] v0.11.48.66: canonical `Evaluation` timing contract used by mature + experimental publication; shared non-overlapping between-pull travel semantics; Mage event-rerank stale timing repaired.
- [x] v0.11.48.67: generic `search_level()` coordinator owns opaque build expansion/dedup, rotation/policy selection, bounded generic gear/stat fixed point, weighted level cost and spawn-safe candidate parallelism. Non-Mage Forever search now uses it; legacy engine adapters temporarily mark bundled candidate optimization to avoid double-running existing class-local fixed points.
- [x] v0.11.48.68: explicit `MageClassModel`; Forever Mage per-level candidates enter the shared `search_level()` kernel while Classic Mage stays historical.
- [x] v0.11.48.69: canonical `LevelFrontier -> solve_routes() -> DecisionResult` is the single route/publication authority; Hunter endpoint routes cannot disappear from an independent publication frontier.
- [x] v0.11.48.70: explicit Forever Mage/Hunter/Druid/Paladin ClassModel adapters, one ruleset-level Forever runner entrypoint, class-owned Mage event hooks, and one shared DecisionResult publication pipeline. Historical analytic-vs-continuity search strategies remain internally distinct behind `ClassModel.runner_strategy()`; no class-name dispatch remains in runner orchestration.
- [x] v0.11.48.71: cross-class L20 fidelity audit + shared recovery authority. Mage/Hunter/Druid/Paladin ordinary sit recovery now enters `solve_recovery()`; Hunter private recovery math was removed and its Spirit regen obeys the combat 5SR while MP5 continues; Mage deterministic recovery/travel semantics were aligned; Paladin/Druid recovery inputs were made scorer-consistent; bounded fixed-point exhaustion publishes the best actually scored state. Mage's bounded independent L20 analytic search is ~197 mobs/h and the event-audited Ice Lance corridor is ~197 mobs/h; the residual gap is now primarily combat-side rather than a known timing-shape mismatch.
- [x] v0.11.48.72: Mage deterministic structural screening carries expected armor-mitigated HP loss into shared recovery and Druid harmful spells use the same-level spell-hit baseline. **Superseded source conclusion:** `.72` treated the raw public Wrath tooltip as current server damage; `.73` corrects this with dated beta-build tuning rather than deleting the raw tooltip fact.
- [x] v0.11.48.73: raw public spell facts and dated Forever beta tuning are separate authorities. The Sep-24 Wrath `~50%` base-damage buff is applied at scoring time before SP; raw tooltip rows remain unchanged. Mage wand finishing now consumes the canonical SQL wand, a sourced item-school overlay, and the ranged-weapon hit table. Deterministic Mage screening now prices contact/pushback that begins during a hard cast instead of requiring melee at cast start.
- [x] v0.11.48.74: Forever beta build/as-of is first-class run semantics. Job/service/CLI execution, tuning resolution, numeric PnP cache hashes, checkpoint compatibility, DecisionResult publication and listener surfaces all carry the same build identity. Pre-.74 artifacts map explicitly to the 2026-10-02 legacy snapshot rather than silently becoming current.


## Next fidelity slice after v0.11.48.73

- **DONE v0.11.48.74 — Forever build identity / reproducibility:** explicit `forever_build_as_of` now drives tuning, numeric cache/checkpoint cohorts and publication/listener metadata; pre-.74 artifacts map explicitly to 2026-10-02.
- **Mage event-vs-deterministic residuals:** event remains finalist authority. Expand only bounded mutation tests around stochastic roots/contact if route retention shows a real pruning miss; do not force backend numerical equality.
- **Wand provenance:** weapon school is not present in the canonical item SQLite schema. Keep the small sourced item-id overlay for now; ingest school into the catalogue only through an explicit schema migration/source refresh.
- **Druid:** keep L46 Wrath raw base damage unknown until a trusted source exposes it; the dated 1.5x tuning layer must not be used to invent the hidden raw row. Moonfire periodic-crit behavior remains separate.
- [x] **v0.11.48.75 base-stat fidelity:** pinned Tauren Druid and Undead Paladin level-1 Spirit anchors plus vanilla class level progression; production recovery now separates base Spirit, item Spirit, base regen and MP5 before entering the shared solver.
- Mage Blizzard/AoE remains a server-profile-dependent opt-in comparison; do not fold it into default single-target L20 throughput.


## Next fidelity slice after v0.11.48.75
- Keep the new base-stat authority narrow. Add other races only from target-server starting-stat evidence; do not import expansion-era race tables wholesale.
- Druid L46 Wrath raw damage remains unknown. Do not infer it from the dated 1.5x tuning layer.
- [x] **v0.11.48.76 capability plumbing:** Mage Blizzard/AoE is an explicit per-run server-profile opt-in through CLI/service; enabled runs fail closed instead of publishing single-target output as AoE. The actual AoE geometry/channel/policy scorer remains the next feature slice.
- Hunter L21-L60 remains source/mechanics work; keep L20 verification cap honest.
- Architecture cleanup should peel bundled policy/gear optimization behind ClassModel hooks only when it naturally accompanies class fidelity work; no new platform megarefactor.

## v0.11.48.88.2 completed · version-aware history hygiene
- [x] producer-version stamp on every newly-created optimizer job
- [x] service exposes running software version
- [x] old completed/failed queue rows hidden by default but retained
- [x] old publications hidden by default with explicit STALE fallback when no current publication exists
- [x] no history/artifact deletion
- [x] bounded regression gate + JS syntax + canonical DB invariant

## v0.11.48.89 completed · stat weights ALWAYS contract
- [x] canonical scorer-state stat-weight authority independent of spec-matrix lookup
- [x] deterministic scorer-state fingerprint + cache
- [x] endpoint-only Druid L30 regression rehydrates real weights
- [x] normal listener selector cannot expose an unweighted supported row
- [x] stale experimental rows without exact gear are history-only rather than silently rescored with different gear
- [x] current spec-matrix/per-level publication treats missing weights as a correctness failure
- [x] representative Mage / Paladin / Druid / Hunter contract gate
- [x] NEXT: I02 Druid build-70170 current talent schema

## v0.11.48.90 completed · Druid 1.60.1.70170 talent schema
- [x] current 52-node Druid tree pinned to TalentsForever build 1.60.1.70170
- [x] Feral: Shredding Attacks moved to 10-point row; Shifting Power + Improved Shifting Power added with current prerequisites
- [x] King of the Jungle removed from current rules; old serialized non-zero field is rejected, never silently translated
- [x] Tiger's Fury removed from current Cat model; Shifting Power replaces it as bounded cooldown + mana-sustainable Energy input
- [x] exact TalentsForever reference allocations validated against runtime schema before use/publication
- [x] normal listener route rows enforce one talent point per level; partial L30 13/21 state is non-selectable
- [x] I01 always-present stat weights regression still passes on current-schema full-point Druid state
- [x] NEXT: I03 `Compare to build` → arbitrary TalentsForever URL


## v0.11.48.91 completed · Compare to build → TalentsForever URL
- [x] listener accepts a pasted TalentsForever build URL and preserves the original clickable source link
- [x] URL allocation is decoded against the active class talent schema; malformed/cross-class/current-schema-invalid links fail clearly
- [x] external build is challenger-only: never search/frontier/route authority
- [x] same-gear mode holds the optimizer's exact published item IDs fixed and lets the challenger reselect legal gameplay/policy
- [x] own-optimized-gear mode runs the challenger through the same class gear fixed point/scorer
- [x] optimizer and challenger both always expose canonical stat weights
- [x] mobs/h delta, kill/recovery/travel delta, rotation, talent divergence, gear assumption and provenance are shown together
- [x] if challenger wins, listener surfaces a possible search/model coverage gap instead of hiding it
- [x] known exact 36/0/15 Druid reference now carries source-backed 51-point leveling order, enabling honest per-level prefixes
- [x] arbitrary URLs never invent a lower-level path: final-allocation-only links compare only at their encoded level
- [x] stored exact reference builds use the same comparator via `Compare this build`
- [x] M0 critical usability milestone CLOSED; NEXT I04 Hunter pet-family active ability fidelity

## v0.11.48.92 planning checkpoint
- M0 I01–I03 DONE.
- M1 I04 DONE: family-constrained Hunter pet active-skill authority.
- NEXT: I05 Summon Hawk, then I06 Survival melee/trap, I07 Hunter closure.

## v0.11.48.93 completed · Hunter Summon Hawk bounded implementation
- [x] source-pinned trained ranks: L25 32 + 5% RAP / 80 mana; L36 47 + 5% RAP / 105 mana (plus L48/L60 table for future levels)
- [x] source-pinned instant / 6s cooldown / 18s hawk duration / max 2 active / shared cooldown with Arcane Shot
- [x] source-backed H/H/Arcane 18s cadence replaces independent Arcane spam when Summon Hawk is active
- [x] source-backed Unleashed Fury + Ferocity hawk modifiers represented conservatively in the initial-strike lower bound
- [x] mana cost is charged; Efficiency is not silently applied to Summon Hawk
- [x] spawned hawk continuing-assault attack table remains explicitly unpriced rather than fabricated
- [x] Hunter focused suite 62/62 PASS; canonical DB restored exact
- [x] NEXT: I06 Survival melee/trap policy
## v0.11.48.93.1 completed · listener selection-state regression hotfix
- [x] per-level-only publications now contribute their latest published level as a valid listener target
- [x] class / target / route changes discard stale selector state and land on the latest valid inspect level
- [x] Druid L11→30-style publication yields Target L30 → per-level fastest → Inspect L30 instead of empty selectors
- [x] Mage-only Ice Lance validation button is hidden and disabled for non-Mage classes; stale panel content is cleared
- [x] Compare-to-build surface remains present and I01 stat-weight hard contract remains covered
- [x] focused gate 15/15 PASS; JS parse PASS; canonical DB restored exact
- [x] NEXT: I06 Survival melee/trap policy


## v0.11.48.93.3 completed · listener named-route truth + local rendered smoke
- [x] Druid named-route publication is fail-closed: `Feral · Cat` cannot expose a Bear scorer row, and `Feral · Bear` cannot expose Cat state
- [x] route-specific fixed-route spec matrices are written/read inside service attempt state via `WOW_SIM_STATE_BASE`
- [x] canonical route rows merge endpoint talent continuity with route-specific scorer objective/profile/gear/timing/stat weights
- [x] listener and TalentsForever comparator consume the same validated canonical route row authority
- [x] Feral Cat L30 now renders Cat / canonical Druid Feral gear / pull 1 / 203.8 mobs/h; Bear remains a separate 249.5 mobs/h row
- [x] stat weights on the Cat row come from that same fixed Cat scorer state (Str=1.00 reference; weapon DPS≈4.83× Str, Agi≈0.43× Str in the saved L30 fixture)
- [x] stored reference defaults to the current talent family instead of unrelated Restoration
- [x] real local listener HTTP process + headless Chromium UI loaded successfully; class/target/route/level all populated; 9/9 rendered-state checks PASS; state JSON + screenshot saved
- [x] `.93.2` was an internal unshipped iteration; `.93.3` additionally pins the scorer objective into the matrix row so stat-weight fingerprint/baseline cannot inherit the endpoint scorer objective
- [x] no gameplay mechanics changed; NEXT remains I06 Survival melee/trap policy


## v0.11.48.94 completed · I06 Survival melee/trap bounded policy
- Added competing Survival melee/trap scorer candidate without GCD permutation search.
- Source-pinned Raptor Strike L16/L24/L32/L40, Immolation Trap L16/L26/L36, Expose Prey -> Mongoose Bite and Lacerating Strikes.
- Clever Traps, Survival Tactics, Resourcefulness, Survivalist's Discipline, Savage Strikes, Predator's Edge and Lightning Reflexes affect the bounded policy.
- Counterattack and Strider Kick remain explicit fail-closed gaps where reactive cadence/base-mana authority is missing.
- NEXT I07 Hunter L21-40 closure/capability matrix.


## Hunter L21–40 closure v0.11.48.95
- CLOSED as bounded planning fidelity through L40.
- Verified behavioral ceiling stays L20.
- Planning ceiling is L40 with explicit capability matrix.
- Remaining unpriced/unmodeled Hunter mechanics are visible fidelity gaps, not blockers to M1 closure.


## Druid Cat combat/resource closure v0.11.48.96

- I08 DONE. Cat is now a first-class finite-target resource model rather than an averaged DPS derivative.
- Energy starts full, regenerates continuously, respects the 1s Cat GCD, and never goes negative.
- Combo points are generated by modeled CP builders/Rake and consumed by 5-CP finishers.
- Bounded candidates score Rake on/off and Rip/Ferocious Bite where trained; shortest modeled kill wins.
- Blood Frenzy, Berserk, Ferocity, Savage Fury, Predatory Instincts, Rend and Tear, Feral Swiftness and Shifting Power flow through the Cat model.
- Omen proc rate and solo Shred uptime remain fail-closed/uncredited.
- NEXT: I09 Bear combat/survival closure.


## Druid Bear combat/survival closure v0.11.48.97
- I09 DONE. Bear survival is an explicit throughput input, separate from offensive DPS.
- Armor, Thick Hide, +Defense/Natural Reaction avoidance, HP and Frenzied Regeneration feed lethality/recovery.
- Post-mitigation incoming damage feeds the explicit server-profiled incoming-Rage proxy; provenance stays visible.
- Multi-pull is bounded to 1–3 and now fails closed to single-target when no verified Swipe rank exists.
- NEXT: I10 shared Cat/Bear form/recovery authority + mandatory real-listener I06–I10 screenshot gate.


## Druid shared stateful recovery closure v0.11.48.98
- I10 DONE. Cat/Bear no longer force full recovery after every mob/pack.
- HP carries through a mob chain until the next identical pull would be unsafe; only then is one shared recovery event paid and amortized over completed mobs.
- Cat Energy carries target-to-target and regens during travel; combo points remain target-local.
- Listener exposes the recovery cycle instead of only an opaque recovery/mob number.
- Mandatory I06-I10 fresh local service/listener checkpoint PASS with Cat, Bear and Hunter Survival screenshots.
- NEXT: I11 Druid closure.

## I24 — Continuation input + on-demand corridor calculation
- Accept current talents as a TalentsForever URL in addition to allocation text; parse the exact current allocation/progression from the source.
- When the exact-current-allocation corridor is absent from the preserved frontier, keep correctness fail-closed but offer **Queue required calculations** instead of dead-ending.
- Queue the canonical class search needed to cover that corridor; do not invent a continuation while the job is pending.
- When the publication completes, surface the newly available no-respec continuation automatically/current-version-safely.


## v0.11.48.112 — I24 DONE
Continuation accepts TalentsForever URLs through server-side exact-schema parsing. Missing exact current-talent corridors remain fail-closed and now offer Queue required calculations, which submits a bounded deep canonical recovery search while retaining the exact current-allocation constraint as job metadata. I21–I24 are complete; next work returns to the remaining gameplay/fidelity backlog.


## v0.11.48.114 — Paladin weapon-slot equal-budget fidelity DONE
- Body-slot equal-budget projection remains the general stat-mix authority and still excludes weapon DPS.
- Added canonical weapon peer exchange estimator using same hand-count + item level + quality groups from the pinned Forever SQLite catalogue.
- Ret/2H and Protection/1H use distinct weapon-slot domains chosen from the actual selected gear style.
- Shared stat-weight schema now supports named equal-budget domains without overwriting native gradients or the general body rank.
- Listener surfaces the weapon-slot rank separately (`weapon-slot 1H/2H`) so weapon DPS is never visually presented as though it bought the same body-slot budget as Strength/Intellect/SP.
- Focused regression also refreshed two stale pre-SQLite Paladin reroll expectations to the current canonical SQLite slot-reroll contract.
- NEXT gameplay/itemization slice: Druid canonical catalogue L20 gap closure / real named-item coverage (item catalogue I5), unless a higher-priority concrete fidelity bug appears.

## G50i — v0.11.48.190 (2026-10-09)

Explicit native generic queue submission and bounded status/inspect in listener DONE, 47 focused tests PASS. G50 remains OPEN because source-only queue probes are not the required generic 1–60 optimizer. NEXT G50j: functional Druid LevelFrontier L12 gap and one tested native step, not more queue infrastructure. Fidelity/reference backlog remains independent.
