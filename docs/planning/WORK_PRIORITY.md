# WORK PRIORITY — live M1 queue

Refreshed against main `faee286dde1bc02cbb7e315d3770ddbda627a44b`. Canonical ledger blob: `5cab5f4e4ae87db153730bd3bb02149eae3cdde6`; scoreboard script blob: `93b3f38c4f663e742d154f7ad90a7b05e0c4defc`.

## M1 scoreboard

- **M1 measured: 2.2041% (float=0.0220405148)**; **29.358 / 1,332** measured gate-equivalents; **23 PASS / 11 active PARTIAL**.
- Paladin L20 unrestricted P3 is official **PARTIAL 154/210** from [Merge recorder #41819051081](https://github.com/dosibjrn/forever-sim/actions/runs/41819051081). Shaman L20 remains **PARTIAL 93/204**; final Intellect no-record [#41821688601](https://github.com/dosibjrn/forever-sim/actions/runs/41821688601) did not improve it.
- Merge alone launches trusted recorders and writes `M1_PASSES.tsv`. No other agent edits the ledger or claims unrecorded float.

## Work1 — Priest L20 unrestricted P4/P5 ([#817](https://github.com/dosibjrn/forever-sim/issues/817))

- Official baseline [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303): both gates BLOCKED, zero complete paid screens and zero source-action casts.
- Work1's existing MythicSim [PR #10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10) remains DRAFT. Latest reported commit [954885c](https://github.com/dosibjrn/mythicsim-forever-engine/commit/954885c88dee10791867ba010ef2ca2e54e4022f) adds source-selected Priest L20 spell ranks; exact-HEAD compile/prepare/sim has not yet been reported. Older smoke [#41812788713](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41812788713) validates only the older `a55a0202` head.
- **Next:** validate the current native head with compile plus a real Priest L20 prepare/sim request; fix its first actual refusal. Then connect the actual L20 actor to the existing paid whole-build and 2D/source-action screen. No L60 proxy, GameIR/SQLite fallback or heavy search before the real actor and source-action screen work.

## Completed Work2 attempt — Shaman L20 unrestricted P3 Intellect ([#871](https://github.com/dosibjrn/forever-sim/issues/871), [closed PR #883](https://github.com/dosibjrn/forever-sim/pull/883), [closed PR #884](https://github.com/dosibjrn/forever-sim/pull/884))

- Exact-HEAD selected-engine no-record [#41820628935](https://github.com/dosibjrn/forever-sim/actions/runs/41820628935) and final exact-head no-record [#41821688601](https://github.com/dosibjrn/forever-sim/actions/runs/41821688601) both leave Shaman P3 at **93/204 PARTIAL**. Spell Power is positive; Intellect is **NO_POSITIVE_SOURCE_POLICY_WITNESS**.
- The final PR #884 run built the selected engine and tested native ItemSparse Intellect deltas **47** and **25**. Intellect remained **0.0**; total paid work was **38/44**. The paid objective is combat-only and does not measure the Intellect-to-mana recovery benefit; this is a measured negative, not an engine failure.
- Maintenance [#41821688630](https://github.com/dosibjrn/forever-sim/actions/runs/41821688630) passed **526 tests** and generic source-paid [#41821688606](https://github.com/dosibjrn/forever-sim/actions/runs/41821688606) passed **317 tests**. #871 is closed as completed; PR #883 is closed as a duplicate and PR #884 is **closed unmerged**. No Merge recorder and no M1 increase; do not repeat or merge this witness path.

## Next Work2 — Paladin L20 unrestricted P3 paid-winner Agility/Intellect witness ([#885](https://github.com/dosibjrn/forever-sim/issues/885))

- **Unblocked from latest main:** Shaman #871 is closed and both PRs #883/#884 are closed unmerged; do not reuse either branch.
- Official Paladin baseline [#41819051081](https://github.com/dosibjrn/forever-sim/actions/runs/41819051081): **PARTIAL 154/210**. The actual report's only witness was Agility through `paladin:source_seed`; it spent 3 evaluations and failed with `BASELINE_NO_EVALUATION`. Intellect was not attempted. The already-paid winner's opening sequence is `seal_of_fury:1311656` + `judgement:20271`.
- Current `tools/wf_gate_p3_live.py` offers a paid search winner as a witness candidate only for Mage L30/Shaman L20. Paladin's exact paid winner is not passed to the witness helper, so the remaining budget is spent retrying the unexecutable source-IR policy. The existing `paid_search_winner_baseline()` has strict prefix/selected-action/fallback/guarded/provenance checks; do not weaken them. The existing native item-sized delta helper is also not enabled for Paladin L20 despite its native ItemSparse item list.
- **Next:** from latest main, prove whether Paladin's exact paid winner passes the existing strict baseline validator. If it does, offer that winner first to the paid witness path (Agility first, Intellect only if budget remains) and use real native top-five item-sized deltas. If the validator rejects it, report the exact invariant and stop; no bypass, generic delta fallback, invented action or extra budget. Keep the 44-evaluation cap.
- Run one changed-HEAD no-record light P3 producer. Require a positive derivative and more than 154/210 comparable assertions before Merge is asked for one official recorder. Otherwise no recorder and no ledger change. Each additional verified assertion would contribute `1 / 210 / 1332` M1 float (about **+0.0003575 percentage points**); the actual count and result are unearned. At most 56/210 remains before a full P3 PASS (+0.0200 pp), not a forecast.
- The separate `mean_weapon_hit_damage` residual is outside #885; it needs a real equipped-hit perturbation, not a guessed alias for weapon DPS.

## Parked alternatives and guardrails

- Mage L30 unrestricted P3 is **PARTIAL 129/224** from [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067); no narrower source-backed repair currently outranks the Paladin follow-up. Use the canonical ledger rather than the stale 44/224 text in #818.
- Hunter L20 P3 [#827](https://github.com/dosibjrn/forever-sim/issues/827) had two trusted attempts BLOCKED with zero source evaluations; do not rerun unchanged.
- Druid L60 Balance P7.4 is PASS; Druid L30/L40 P6 remain 200/200 PARTIALs with no demonstrated cheap next increment.
- Active gates only: P3–P6 and P7.1–P7.5. P1/P2 are retired. No HPS/TPS witnesses, MythicSim self-validation, duplicate unchanged runs, invented weights or fabricated M1 rows.
