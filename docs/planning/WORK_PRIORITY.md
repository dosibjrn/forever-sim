# WORK PRIORITY — live M1 queue

Refreshed against main `57f41743fdf5231d62c432fa2e24b4232ac47a82`. Canonical ledger blob: `8a93be655f200dd48206996496373b0c230fb735`.

## Current M1 scoreboard

- **M1 measured: 2.1391%** (`measured_fraction=0.0213906002`).
- **28.492 / 1,332** measured gate-equivalents; **23 PASS / 10 PARTIAL** active-scope gate rows (retired P1/P2 partial rows excluded).
- **0 / 148** certified checkpoints. The measured float is diagnostic coverage, not certification. Only Merge writes `M1_PASSES.tsv`.
- **Prio recheck — selected next Work1 action: `shaman:20:unrestricted:P3` Spell Power witness (#859).** The official Shaman row is now PARTIAL **66/204** and the exact remaining source-policy defect is a missing positive Spell Power witness for existing `lightning_bolt:915`: `native_spell_coefficients_applied=[]`, while native PreparedV2 coefficient transport is currently wired only for Mage L30. Extending that existing source-backed path is narrower than implementing the new native Priest L20 actor plus paid P4/P5 screen (#817), so it is the better expected M1 gain per work. Each added comparable assertion is **+0.000368 pp**; the count is unknown until a changed-HEAD run. #817 remains Work1's next task after #859; Work2 #845 remains independent. Canonical ledger blob `c45f50ea4fe1aad3d9cf972d24a1981b823600ad`; M1 measured **2.1391%** (`float=0.0213906002`), 28.492/1,332, 23 PASS / 10 PARTIAL, 0/148 certified.

## Immediate dependency-ordered queue

### 1. Work1 — Shaman L20 unrestricted P3 source-backed Spell Power witness

- New follow-up [issue #859](https://github.com/dosibjrn/forever-sim/issues/859), separate from the now-completed native ItemSparse integration #847. The official Merge recorder [#41800797285](https://github.com/dosibjrn/forever-sim/actions/runs/41800797285) recorded **PARTIAL 66/204** (32.35%) on merge SHA `f3ae57acdd7029c5799bd720cb5ab2f212c3ef21`; the P3 gate remains FAIL. The report used 41 paid evaluations, 1,955 native legal items, 17 slots and 85 top-five items.
- The first narrowly actionable residual is `NONPOSITIVE_RELEVANT_WEIGHT:spell_power`. The paid witness returned `NO_POSITIVE_SOURCE_POLICY_WITNESS` for `forever:shaman:hybrid@20`; its actual source actions include `lightning_bolt:915` and `rockbiter:8019`. The report has `native_spell_coefficients_applied=[]` and `native_paid_winner_spell_probe_enabled=false`. In `tools/wf_gate_p3_live.py`, the existing native PreparedV2 coefficient transport is currently enabled only for Mage L30 unrestricted.
- **Next action:** query the selected MythicSim Rust engine for the exact native coefficient of the existing source-ranked Shaman `lightning_bolt:915` action; attach it only to that matching IR action, then enable the existing paid-winner stat witness only when that exact native coefficient is present. No hand-entered coefficient, synthetic action, level-60 actor stats, guessed weight or independent MythicSim mechanics audit.
- **Smallest verification:** focused adapter regression for exact rank matching and fail-closed missing/refused coefficients; then one changed-HEAD no-record Shaman L20 P3 producer within the 44-evaluation cap. Require `native_spell_coefficients_applied` to contain `lightning_bolt:915`, a `MEASURED_POSITIVE_SOURCE_POLICY_WITNESS`, `real_measured_stat_weights.spell_power>0`, and `pass_count>66` with the same 204 denominator. If native source data or a positive witness is unavailable, preserve the 66/204 high-water and report the exact result. Merge alone may record a real comparable increase.
- Each added comparable assertion is **+0.000368 pp**; the maximum remaining room from 66/204 to full P3 PASS is **+0.05079 pp**, not a forecast. The actual number of SpellDamage assertions affected is unknown until the producer runs. Keep this issue limited to Spell Power; Stamina/Strength, Agility/Intellect and other unmapped axes are separate failures, not scope for speculative broadening.

### 2. Work1 — Priest L20 unrestricted P4/P5 native level-aware actor (after #859)

- Existing owner task [#817](https://github.com/dosibjrn/forever-sim/issues/817). The official light run [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) invoked both gates but returned **BLOCKED** at `P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED`: zero complete paid screens and zero source-action casts.
- MythicSim draft PR [#10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10) only adds the explicit `proto.Player.level` field and refuses unsupported L20 preparation; it does **not** yet create a level-20 actor or paid screen.
- **Next action after #859:** implement the minimum MythicSim-owned, source-backed Priest L20 race/class base stats and level-dependent conversions; prepare a real level-20 native actor; connect it to the existing paid whole-build evaluator and real 2D/source-action screen. Then run one changed-HEAD no-record light P4/P5 producer showing complete paid screens and positive source-action casts. No L60 proxy, guessed stats, Forever GameIR/SQLite fallback, or independent MythicSim-mechanics audit.
- If both gates eventually reach 2/6 comparable paid-screen behaviors, their conditional combined M1-float opportunity is **+0.05005 pp**. Not earned. Keep #817 scoped to Priest; Work2 may reuse the actor for Paladin only if the native contract naturally supports that class.

### Parallel Work2 — Paladin L20 unrestricted P3 source-backed actor and weapon

- Existing owner task [#845](https://github.com/dosibjrn/forever-sim/issues/845), independent of Work1's #859/#817 sequence but potentially able to reuse #817's native L20 actor.
- Work2 PR [#851](https://github.com/dosibjrn/forever-sim/pull/851) fixed the first production search failure: no-record run [#41799055428](https://github.com/dosibjrn/forever-sim/actions/runs/41799055428) moved source-naked from 0 attempts/0 evaluated to **12 attempts/11 evaluated**, selecting sourced `holy_strike:1866`, within the 44-evaluation cap. The actual P3 result remains **BLOCKED** (`P3_SOURCE_COOLDOWN_WINNER_HAS_PROXY_ACTOR_OR_WEAPON`), with **zero eligible source evaluations**, because actor base stats and the 14-DPS weapon are proxies.
- **Next action:** establish source-backed Paladin L20 actor and equipped-weapon facts in MythicSim; reuse #817's native level-aware actor if its real source contract supports Paladin, rather than creating another Forever actor provider. Then run one changed-HEAD no-record P3 producer proving eligible paid item/stat scoring. No proxy credit, synthetic action, global default change or unchanged official recorder.

## Completed / no unchanged redispatch

- **Druid L60 Balance P7.4** current-code PASS on both post-#840 heavy runs [#41786536534](https://github.com/dosibjrn/forever-sim/actions/runs/41786536534) and [#41786566461](https://github.com/dosibjrn/forever-sim/actions/runs/41786566461); the canonical receipt remains the single accepted row. No further P7.4 run.
- Hunter L20 P3: `BLOCKED_NO_NAKED_SUCCESS`, zero paid source evaluations; no unchanged retry.
- Mage L20 P3: preserve the 88/224 high-water; no unchanged retry.
- **Mage L30 unrestricted P3:** Work2 PR #831 merged as `7c46654`; official recorder [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067) completed SUCCESS and recorded **PARTIAL 129/224** (57.59%), up from 85/224. The exact no-record result used 44 paid evaluations and scored 85 native top-five items; Spell Power, Intellect and Hit are positive. Gate remains FAIL; no unchanged rerun. The canonical M1 score is now 2.1391%, 28.492/1,332 measured equivalents, 23 PASS / 10 PARTIAL, 0/148 certified.
- **Shaman L20 P3 native ItemSparse task #847 is complete:** PR #855 merged recorder routing (`82442d7`) and PR #854 merged the native caller (`f3ae57a`); no-record producer [#41800458135](https://github.com/dosibjrn/forever-sim/actions/runs/41800458135) reached paid scoring, and official recorder [#41800797285](https://github.com/dosibjrn/forever-sim/actions/runs/41800797285) recorded **PARTIAL 66/204**. The original no-legal-items failure is superseded. Do not repeat #41789474594 or the unchanged 66/204 producer; the narrow Spell Power follow-up is tracked separately in [#859](https://github.com/dosibjrn/forever-sim/issues/859).

## Operating constraints

- Merge alone dispatches official M1 recorders and writes `M1_PASSES.tsv`; Prio maintains this queue and submits requests on existing owner issues.
- Mage L30 P3 official recorder [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067) is terminal SUCCESS and its PARTIAL 129/224 receipt is in the canonical ledger. Do not duplicate it; Merge alone writes future M1 receipts.
- Prioritize real active P3–P7.5 production progress. No P1/P2 work, retired GameIR search runners, HPS/TPS witness work, MythicSim self-validation, invented positive weights or fabricated M1 rows.
