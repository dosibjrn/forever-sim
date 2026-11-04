# FOREVER SIM — active M1 work queue

**Policy:** maximize credible incremental M1 measured-float gain per total implementation, validation and compute time. Active gates: P3–P6 and P7.1–P7.5, 1,332 pairs. Only Merge dispatches trusted M1 measurements and updates `M1_PASSES.tsv`. Retired P1/P2, new GameIR or parallel Warcraft legality, and unrelated HPS/TPS work are not priorities. A PASS adds 1/1332; a PARTIAL adds only its actual eligible high-water improvement. Never presume PASS from an unrun gate.

**Latest main scoreboard:** M1 measured: **1.4009% (float=0.0140093374)**; **15/1332 accepted PASS gates; 0/148 certified checkpoints**. Partial-inclusive diagnostic only; recomputed from current [ledger](M1_PASSES.tsv) with [scorer](../../tools/m1_progress.py). The increase from 1.3349% is the genuine Druid L20 unrestricted P4 PASS below, not a forecast.

## #1 — Merge: one independent full Druid L20 unrestricted P5 measurement — [#761](https://github.com/dosibjrn/forever-sim/issues/761)

- **Baseline:** `druid:20:unrestricted:P5` PARTIAL **3/25** from bounded six-second probe [#41478424292](https://github.com/dosibjrn/forever-sim/actions/runs/41478424292); its report explicitly says the full 300-second search and independent 100-mob finalist were not executed.
- **New pass-path evidence:** the same checkpoint's P4 genuinely PASSed in [#41750754719](https://github.com/dosibjrn/forever-sim/actions/runs/41750754719): 29.998065067s, **231** unique paid full builds, 231 complete paid screens, complete 100/100-mob finalist, 10.3706475532s/mob; runtime `gsim-0.11.48.289`, source revision `127071d94b5e511e8f4a5a3a61e64583acac22cf3201b7a7dc84f8593558d8e0`.
- **Next:** inspect live/recent Actions for an identical full P5 run; if clear, once run trusted `/m1-run --heavy druid:20:unrestricted:P5` on current main. Keep it cold/independent on the same objective/source/runtime. P5 requires 300 actual wall seconds, `N300 >= 2 × N30` and one complete 100-mob finalist; with `N30=231`, require **at least 462** unique paid full builds. Only Merge records the actual producer verdict.
- **Why #1:** current PARTIAL leaves potential **unearned** `(1-3/25)/1332 = 0.0006606607` measured fraction (**+0.06607 pp**). The accepted P4 gives this same-source P5 a credible pass path; one 300-second measurement is cheaper than first implementing the separate L30 source repair. No PASS is presumed; do not repeat an unchanged failure.

## #2 — Work1: repair reproduced Druid L30 unrestricted P4 source-initialization FAIL — [#753](https://github.com/dosibjrn/forever-sim/issues/753)

- **Actual RED:** official full [#41750059038](https://github.com/dosibjrn/forever-sim/actions/runs/41750059038) on `main@fc5e6740` **FAILed before search**: `SOURCE_COLD_CHECKPOINT_ABILITY_DB_MISSING`. `tools/wf437_direct_budgeted_run.py` selects nonexistent `data/forever/staged_druid_l30_talents_70338.sqlite` for this checkpoint; other levels use the canonical source path. This is not a gameplay/optimizer FAIL. Main M1 high-water remains PARTIAL **3/35**.
- **Next implementation:** remove the dead L30-only staged-file dependency in the existing active full-search runner; reuse canonical/native facts only when they actually supply the needed L30 facts. Preserve source identity, candidate legality, talent-unlocked policy execution, independent 30s cold search and 100-mob semantics. No new Python GameIR/source database, duplicate Warcraft legality or extra gate. PR [#758](https://github.com/dosibjrn/forever-sim/pull/758) is merged (receipt-only, `M1 affected gates: none`), so Work1 can start now.
- **Why #2:** the reproduced setup defect has a concrete repair path and potential **unearned** `(1-3/35)/1332 = 0.0006864007` fraction (**+0.06864 pp**). Work1 can implement in parallel with #761; after merge, Merge performs one official full P4 acceptance. No unchanged reruns.

## #3 — Work2: native Priest L20 unrestricted P3 legal gear options — [#754](https://github.com/dosibjrn/forever-sim/issues/754)

- **Actual RED:** official [#41747651321](https://github.com/dosibjrn/forever-sim/actions/runs/41747651321) reached `P3_NO_LEGAL_ITEMS_IN_CURRENT_DB`. No Priest PASS/PARTIAL. Current Forever SQLite/Python class-eligibility list is empty for the tested checkpoint.
- **Next implementation:** expose the minimum read-only legal gear-options query from pinned MythicSim Rust item/legality authority; route P3 top-five-ilvl candidates through it; verify Priest L20 real P3 progress with focused native/Forever integration and one justified official result. No Priest rows or parallel Python legality. Preserve Mage L20 P3 PARTIAL **57/155** and its actual weight blockers.
- **Independent of Work1:** no reassignment or takeover of Work2's fork/Forever PRs.

## Work1 follow-up — Druid L60 Balance P7.4, retained under [#131](https://github.com/dosibjrn/forever-sim/issues/131)

- [#41746867119](https://github.com/dosibjrn/forever-sim/actions/runs/41746867119) completed the 300.000150s search and frozen 1,000 fights: **FAIL 704.6605/720.9117 DPS (97.75%)**, retained PARTIAL. Paid Balanced winner selection did run; hard-coded `paid_stochastic_*=0` fields are not evidence of missing finalists.
- [PR #758](https://github.com/dosibjrn/forever-sim/pull/758) has now merged the receipt-only correction exposing actual `paid_balanced_finalists` / `paid_balanced_confirmed` counts and bounded Balanced finalist failures. No unchanged heavy rerun; use the real Balanced counts, finalist failures and source-control refusals for the next substantive search change. Maximum remaining M1 credit is only ~**+0.00169 pp**, below the P4/P5 opportunities above.

## Independent Clean lane

Clean continues safe dead GameIR/P1/P2 retirement under [#357](https://github.com/dosibjrn/forever-sim/issues/357) and [#359](https://github.com/dosibjrn/forever-sim/issues/359). Preserve active P3–P7.5 callers until a real native replacement exists; cleanup earns no gate credit.
