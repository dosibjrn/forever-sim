# Feature gaps — active work list

This is the short list for implementation work. Historical M47 adversarial artifacts are evidence only; they are not the development queue.

## Mage

- **Ice Lance listener authority mismatch fixed (v0.11.47.24):** v0.11.47.23 fixed candidate retention/event reranking but the Decisions listener still rebuilt `unconstrained` from a historical no-respec frontier, so it could display the 153.0 FBo build while the same retained pool's event validator selected the 170.5 Ice Lance build. The listener's unconstrained milestone route now consumes the runner's exact cumulative DP path instead of silently re-deriving a different path authority.
- **v0.11.47.23 was only a partial Ice Lance fix:** it made the event-winning Ice Lance lane selectable by the runner, but did not wire that runner result through to the endpoint artifact shown by `/decisions`.
- Fireball/Pyroblast attached periodic damage now crits in stochastic, expected and analytic paths (v0.11.47.13); proc side-effects from periodic crits remain intentionally unmodeled until separately sourced.
- Keep HP-aware wand finishing as an optimizer policy; current L20/L40/L60 regressions already cover the implemented behavior.
- Best usable water, Mana Gems and Evocation are already in the shared recovery/continuation path; do not reopen them without a concrete failing case.

## Druid

- Bear Swipe rank damage is verified flat damage on current Forever pages; do not project Cat weapon scaling onto it.
- **v0.11.48.113 completed:** Forever incoming-damage Rage now follows Blizzard first-party semantics: original damage-taken Rage formula, but real Armor/absorbs do not reduce Rage; the formula is evaluated as if Armor always reduced damage by 50%. Avoided attacks still generate no damage Rage.
- Natural Reaction and Thick Hide are modeled from the current Forever talent reference. **Generic +Defense avoidance is now modeled (v0.11.48.12)** through the shared Forever combat-table proxy: bonus Defense adds miss+dodge avoidance for Druid forms, with no parry/block. The exact Forever incoming-damage Rage formula remains open before survivability comparisons are fully authoritative.
- Do **not** model Improved Swipe / Swipe (Cat) by default: the current Forever Beta spellbook/talent snapshot does not contain it. The Wowhead page is inherited SoD-rune data and is not availability proof (corrected in v0.11.47.17).
- **Lacerate is modeled (v0.11.47.18):** ranks 42/50/58, 15-Rage base cost, Shredding Attacks -1/-2/-3 Rage, finite 5-stack bleed ramp, 10% weapon damage per existing stack, periodic crit flag, shared GCD/Rage priority, and excess-Rage Maul fallback.
- **Blood Frenzy is modeled (v0.11.47.19):** current talent identity replaces the stale Primal Fury search key; rank 1/2 gives Bear crits 50/100% chance for +5 Rage and Cat CP-builder crits 50/100% chance for +1 extra CP. The old `primal_fury` field remains load-only compatibility and is not searchable.
- **King of the Jungle is modeled (v0.11.47.20):** Tiger's Fury is credited from level 24 as a 30 s cooldown / 6 s / +15% physical-damage window, and KotJ rank 1/2/3 adds 20/40/60 Energy per use. The deterministic scorer averages the cooldown over the continuous leveling cycle instead of resetting it per mob.
- **Berserk is modeled (v0.11.47.21):** 15 s / 180 s uptime is carried across the leveling cycle. Cat CP builders gain +100 percentage points crit during the window (capped at 100%), affecting direct builder damage and Blood Frenzy CP generation. Bear Primal Bite loses its 6 s cooldown during the window and can hit up to 3 targets. Fear immunity is intentionally not credited to throughput.
- **v0.11.48.113 completed:** the main Bear mechanics gap is closed with Blizzard's fixed-50%-Armor incoming-Rage rule; real mitigation remains exclusively a survival/recovery input.

## Paladin

- Stamina / armor / defense / healing analytical derivatives already exist in the Paladin gradient; keep their local-probe coverage, do not reimplement them.
- **v0.11.48.114 completed:** Paladin weapon DPS now uses a separate real-weapon peer equal-budget domain (1H vs 2H selected from the actual gear style). Body-slot primary-stat budget remains separate; weapon DPS is never assigned the body budget scale.

## Cross-class / platform

- Continue real-item anchors across levels where gear quality can materially change the result.
- Add more classes through the existing class registry only after current-class gameplay gaps above are under control.
- Optimizer service / durable queue / save-load remains platform work, not a substitute for missing mechanics.

## Validation rule

Default development validation is `./run-validation-fast.sh` (or the PowerShell equivalent). It must stay under 15 seconds. The old Druid frozen L20/L40/L60 oracle is historical compatibility coverage and is no longer part of the default fast/release gate. Add a regression when a real bug is found; do not add a new level-specific validation campaign for every surprising result.


## Platform TODO status v0.11.48.24
Optimizer-service architecture/UX and validation are complete through U1–U5 and V0–V5. Gameplay/fidelity gaps above are active again. Keep platform work in regression/maintenance mode unless a concrete service defect blocks gameplay work.

## Item catalogue / itemization — active plan 2026-09-29

- Current sparse class-specific/hard-coded pools are to be replaced by the shared SQLite catalogue described in `docs/plans/ITEM_CATALOGUE_REFRESH_PLAN_v1.md`.
- Wowhead Forever is refresh/verification upstream; optimizer runtime uses the local versioned catalogue snapshot and may fall back to cached values with an explicit listener info indicator.
- Canonical ingestion uses a small fixed class-query set split into three ilvl bands; item rows are deduplicated globally by item id and class usability is relational.
- Missing required level uses a catalogue-derived per-ilvl median from observed `(ilvl, req_level)` pairs. Interpolated fallback is allowed only when an ilvl bucket has no observed samples and remains explicitly tagged as inferred.
- I1-I4 catalogue infrastructure DONE; I5 Druid catalogue integration / L20 coverage acceptance is next.
- First acceptance target after infrastructure: eliminate the current Druid L20 unexplained catalogue gaps with real catalogue candidates, not hand-picked pseudo coverage.
