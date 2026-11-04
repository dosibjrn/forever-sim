# WORK PRIORITY — live M1 queue

Refreshed against main `1cdf1479f85db080439e51b220d62192136e8967` (2026-11-04). Canonical ledger blob: `5cab5f4e4ae87db153730bd3bb02149eae3cdde6`; scoreboard script blob: `93b3f38c4f663e742d154f7ad90a7b05e0c4defc`.

## M1 scoreboard

- **M1 measured: 2.2041% (float=0.0220405148)**; **29.358 / 1,332** measured gate-equivalents; **23 PASS / 11 active PARTIAL**. Diagnostic coverage, not 148-checkpoint certification.
- Official Mage L30 P3 is **FAIL / PARTIAL 129/224** ([Merge #41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067)); the current no-record production run [#41825458652](https://github.com/dosibjrn/forever-sim/actions/runs/41825458652) reproduces 129/224 with 44 paid evaluations. Only Merge launches trusted recorders and writes `M1_PASSES.tsv`.

## Work1 — Priest L20 unrestricted P4/P5 ([#817](https://github.com/dosibjrn/forever-sim/issues/817))

- Official baseline [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303): **BLOCKED**, zero COMPLETE paid whole-build screens and zero source-action casts; neither gate has an M1 row.
- Continue MythicSim draft [PR #10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10), current exact head `2846f6b850eb661a313f27c7698672cdba8a9470`. Engine checks [#41827229552](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41827229552) failed at changed-Rust formatting; actor tests were skipped. Combined native contract [#41827229678](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41827229678) succeeded but does not prove the Priest L20 cast path.
- Next: fix rustfmt, rerun exact-HEAD checks, and prove the native L20 Priest actor plus rank-one Smite cast. Only then promote a tested exact pin and connect it to Forever's paid whole-build + 2D/source-action screen. No L60 proxy, GameIR/SQLite fallback or heavy search before the real actor works.

## Work2 — Mage L30 unrestricted P3 ([#818](https://github.com/dosibjrn/forever-sim/issues/818))

- **Active next implementation.** Official [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067) and changed-production no-record [#41825458652](https://github.com/dosibjrn/forever-sim/actions/runs/41825458652) both show **FAIL / PARTIAL 129/224**. Remaining measured causes include missing Stamina/Strength weights, nonpositive Agility/AP/MP5/Spirit and native unknown-level/unmapped axes; positive Intellect, Spell Power and Hit already work.
- **First action:** prove the actual production `axis_set` before changing code. The P3 provider requests Stamina/Strength, but `source_budgeted_gear.py` filters them through `executable_gear_stats(ir)`; the default executable list omits both, while source conversions/primary facts may add axes. The only Mage-specific Stamina conversion found in the repository is a staged ForeverDB import/test path, not proof of presence in the production default DB. Do not append generic axes, invent zero/epsilon, or guess Strength mechanics. Use only an actual source/native-backed delta in the unchanged paid scorer.
- **Verification:** focused regression plus one changed-HEAD light no-record P3 run with the exact selected engine and 44-evaluation cap. Ask Merge for one official recorder only after a comparable result **greater than 129/224** or PASS. Each additional assertion is **+0.000335 pp**; the remaining 95/224 is an arithmetic **+0.03184 pp ceiling**, not a forecast.

## Merge / parked work

- Paladin L20 P3 [#885](https://github.com/dosibjrn/forever-sim/issues/885) and [PR #887](https://github.com/dosibjrn/forever-sim/pull/887) are **closed unmerged, no gain**: exact-head [#41825755653](https://github.com/dosibjrn/forever-sim/actions/runs/41825755653) stayed 154/210 after two real native Agility perturbations. No recorder and no unchanged rerun.
- Shaman L20 P3 [#871](https://github.com/dosibjrn/forever-sim/issues/871) remains 93/204 with no positive Intellect derivative; PRs #883/#884 are closed unmerged. No between-mob mana proxy or HPS/TPS.
- Mage L20 P3 remains 88/224 after unchanged revalidation; Hunter L20 P3 [#827](https://github.com/dosibjrn/forever-sim/issues/827) was BLOCKED with zero source evaluations; Druid L30/L40 P6 200/200 PARTIALs have no demonstrated cheap additional fraction. No unchanged reruns.
- Active gates only: P3–P6 and P7.1–P7.5. P1/P2 retired. No GameIR replacement, MythicSim self-validation, HPS/TPS proxy, fabricated weights, duplicate M1 writer or manual ledger edits.