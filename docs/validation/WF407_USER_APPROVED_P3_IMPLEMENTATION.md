# WF407 — P3 smoke implementation notes (not a replacement PROCESS)

Authoritative policy: protected `PROCESS_WOW_FOREVER_v1_2026-10-15.md`, SHA256 `ce936f4d6a054333ef92541f1878855179ec8d1732669f7e0b044aa74632c4d5`. The user-approved protected overall target is `OVERALL_PLAN_WOW_FOREVER_v5_APPROVED_2026-10-15.md`, SHA256 `841162fa6817c8c8b20e2804c5e77f9589d167765ad537bdad6daa508e1e5e5a`.

P3 chooses *five highest item-level legal items* per populated slot from `available_items`, tests their actual `item_score` with build-specific weights, and checks known ordinary axes for strictly positive weights only if present in the selected gear. All provided weights must be non-negative and finite when present. Melee/wand/ranged DPS are alternatives. Mean weapon hit weight >0 if the action IDs in the current policy resolve to `WeaponDamageEffect` on actual `GameIRSlice`. Dependency not supplied remains RED, not assumed absent. No attested full Wowhead 1–255 scrape and no modeling of every special effect or 100mob stat derivative is required for P3.

Actual production item scoring now includes source raw Hit/Crit/Dodge/Defense; HP5 (`healthrgn`), parry raw rating, ranged attack power; distinct melee/wand/ranged DPS channels; and melee mean-hit damage. No raw chance/rating conversions or artificial positive fallback values were invented. The special-effect-only item may legitimately score zero for ordinary stat weight.

Druid L20 current real-source diagnostic: 79 selected distinct slot occurrences across 18 slots in 0.09s; historical WF347 stat weights fail currently for Stamina, Spirit, Spell Power, MP5 and unverified rotation/IR dependency. 0/148 accepted. Next W should derive physically meaningful positive source-compatible weights from the actual current policy/actor and rerun this smoke, then P4–P7. Do not change PROCESS or OVERALL PLAN to make current weights pass.

The old `source_class_item_membership_verified` remains available as optional data-quality provenance, but no longer controls P3 preflight.
