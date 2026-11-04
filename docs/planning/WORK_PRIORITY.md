# WORK PRIORITY — live M1 queue

Refreshed against main `0e9862b162df782a19dad2716ee2d1037f11097a`. Canonical ledger blob: `5cab5f4e4ae87db153730bd3bb02149eae3cdde6`; scoreboard script blob: `93b3f38c4f663e742d154f7ad90a7b05e0c4defc`.

## M1 scoreboard

- **M1 measured: 2.2041% (float=0.0220405148)**; **29.358 / 1,332** measured gate-equivalents; **23 PASS / 11 active PARTIAL**; **0/148 certified**.
- Paladin L20 unrestricted P3 is official **PARTIAL 154/210** from [Merge recorder #41819051081](https://github.com/dosibjrn/forever-sim/actions/runs/41819051081). The gate remains FAIL, not PASS.
- Merge alone launches the trusted recorder and writes `M1_PASSES.tsv`. No other agent edits the ledger or claims unrecorded float.

## Work1 — Priest L20 unrestricted P4/P5 ([#817](https://github.com/dosibjrn/forever-sim/issues/817))

- Official baseline [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303): both gates BLOCKED, zero complete paid screens and zero source-action casts.
- Work1's existing MythicSim [PR #10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10) is still DRAFT. Its latest reported commit [954885c](https://github.com/dosibjrn/mythicsim-forever-engine/commit/954885c88dee10791867ba010ef2ca2e54e4022f) adds source-selected Priest L20 spell ranks; **no exact-HEAD compile/prepare/sim validation has been reported yet**. Older smoke [#41812788713](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41812788713) validates only the older `a55a0202` head.
- **Next:** validate the current native head with compile plus a real Priest L20 prepare/sim request; fix the first actual refusal. Then connect the actual L20 actor to the existing paid whole-build and 2D/source-action screen. No L60 proxy, GameIR/SQLite fallback, or heavy search before the real actor and source-action screen work.

## Work2 — Shaman L20 unrestricted P3 Intellect ([#871](https://github.com/dosibjrn/forever-sim/issues/871))

- Official baseline [#41808193281](https://github.com/dosibjrn/forever-sim/actions/runs/41808193281): **PARTIAL 93/204**; Intellect weight is 0.0 and only the native Spell Power witness was attempted.
- Paladin PR #865 and its official recorder are complete; the #871 prerequisite is satisfied. Work2's branch `work2/shaman-l20-intellect-witness-871-20261104` exists.
- **Next:** add only the source-backed Intellect witness after the native Spell Power path, using native item-sized deltas and the existing 44-evaluation cap. One changed-HEAD no-record run must show a positive derivative and more than 93/204 before Merge is asked for its single recorder. No M1 credit is presumed.

## Work2 follow-on — Paladin L20 unrestricted P3 native-sized stat witness ([#885](https://github.com/dosibjrn/forever-sim/issues/885))

- Official baseline [#41819051081](https://github.com/dosibjrn/forever-sim/actions/runs/41819051081): **PARTIAL 154/210**. Residuals include nonpositive Agility/Intellect, missing mean weapon hit damage and unmapped native axes.
- The live provider already selects native ItemSparse for Paladin L20 and has a helper for real item-sized stat deltas, but currently enables that helper only for Mage L30 and Shaman L20. Paladin's zero-weight Agility/Intellect path still uses generic 5/20 deltas.
- **Next after #871 is merged:** enable the existing native item-sized witness path for Paladin L20 Agility/Intellect only. Keep source-authored policies, no generic fallback when native deltas are absent, and the 44-evaluation cap. Run one changed-HEAD no-record producer; request Merge recording only for a real positive derivative and comparable assertion increase. Per additional assertion the maximum partial-inclusive increase is `1 / 210 / 1332` of M1 float (about +0.0003575 percentage points); the actual applicable count and result are unearned until measured.
- The separate `mean_weapon_hit_damage` residual is **not** included in #885; it needs its own real equipped-hit perturbation, not a guessed alias for weapon DPS.

## Parked alternatives and guardrails

- Mage L30 unrestricted P3 is **PARTIAL 129/224** from [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067); no narrower source-backed follow-up currently outranks the active Work2 lanes. The old #818 issue body still has an obsolete 44/224 baseline; use the canonical ledger.
- Hunter L20 P3 [#827](https://github.com/dosibjrn/forever-sim/issues/827) had two trusted attempts BLOCKED with zero source evaluations; do not rerun unchanged.
- Druid L60 Balance P7.4 is PASS; Druid L30/L40 P6 remain 200/200 PARTIALs with no demonstrated cheap next increment.
- Active gates only: P3–P6 and P7.1–P7.5. P1/P2 are retired. No HPS/TPS witnesses, MythicSim self-validation, duplicate unchanged runs, invented weights or fabricated M1 rows.
