# FOREVER SIM — active M1 work queue

**Policy:** maximize credible incremental M1 measured-float gain per total implementation, validation and compute time. Active gates: P3–P6 and P7.1–P7.5, 1,332 pairs. Only Merge dispatches trusted M1 measurements and updates `M1_PASSES.tsv`. Retired P1/P2, new GameIR or parallel Warcraft legality, and unrelated HPS/TPS work are not priorities. A PASS adds 1/1332; a PARTIAL adds only its actual eligible high-water improvement. Never presume PASS from an unrun gate.

**Latest main scoreboard:** M1 measured: **1.3349% (float=0.0133486768)**; **14/1332 accepted PASS gates; 0/148 certified checkpoints**. Partial-inclusive diagnostic only; recomputed from current [ledger](M1_PASSES.tsv) with [scorer](../../tools/m1_progress.py).

## #1 — Merge: one independent low-cost Druid L20 unrestricted P4 measurement — [#759](https://github.com/dosibjrn/forever-sim/issues/759)

- **Baseline:** `druid:20:unrestricted:P4` PARTIAL **3/25** in [#41478424292](https://github.com/dosibjrn/forever-sim/actions/runs/41478424292). The analogous L40 P4 is PASS [#41744549169](https://github.com/dosibjrn/forever-sim/actions/runs/41744549169). The WF437 L20 full path uses ordinary `DEFAULT_DB`, not the missing L30-only staged file.
- **Next:** recheck no identical live/recent run, then **once** run trusted `/m1-run --heavy druid:20:unrestricted:P4` on merged main (or existing dispatch with `allow_heavy=true`). Require the approved cold 30-second whole-build search, talent-unlocked action execution and 100 consecutive mobs. Record only the real producer verdict. Do not repeat an unchanged failure.
- **Why #1:** potential **unearned** increment `(1-3/25)/1332 = 0.0006606607` measured fraction (**+0.06607 percentage points**), with no proven L20-specific source-setup prerequisite. The slightly larger L30 headroom requires a code fix first; P5 is 300 seconds and P7.4 has much less remaining credit.

## #2 — Work1: repair reproduced Druid L30 unrestricted P4 setup FAIL — [#753](https://github.com/dosibjrn/forever-sim/issues/753)

- **Actual RED:** official full [#41750059038](https://github.com/dosibjrn/forever-sim/actions/runs/41750059038) on `main@fc5e6740` **FAILed before search**: `SOURCE_COLD_CHECKPOINT_ABILITY_DB_MISSING`. `tools/wf437_direct_budgeted_run.py` selects nonexistent `data/forever/staged_druid_l30_talents_70338.sqlite` for this checkpoint; other levels use the canonical source path. Previous M1 high-water stays PARTIAL **3/35**.
- **Next implementation:** after safely handing off in-flight [Work1 PR #758](https://github.com/dosibjrn/forever-sim/pull/758), remove the dead L30-only staged-file dependency in the existing active full-search runner, reuse existing canonical/native facts where actually available, and preserve source legality, real paid 30s search, talent-unlocked policy execution and 100-mob semantics. Do not create a new Python GameIR/source database or extra gate. Focused source-initialization regression first; Merge performs **one** post-merge full acceptance if justified.
- **Why #2:** the failure is directly reproduced and potentially unlocks `(1-3/35)/1332 = 0.0006864007` fraction (**+0.06864 pp**, unearned). This is more valuable than a new P7.4 heavy run. Work1 retains its P7.4 issue/PR; this is a documented priority sequencing change, not silent ownership transfer.

## #3 — Work2: native Priest L20 unrestricted P3 legal gear options — [#754](https://github.com/dosibjrn/forever-sim/issues/754)

- **Actual RED:** official [#41747651321](https://github.com/dosibjrn/forever-sim/actions/runs/41747651321) reached `P3_NO_LEGAL_ITEMS_IN_CURRENT_DB`. No Priest PASS/PARTIAL. Current Forever SQLite/Python class-eligibility list is empty for the tested checkpoint.
- **Next implementation:** expose the minimum read-only legal gear-options query from pinned MythicSim Rust item/legality authority, route the P3 top-five-ilvl candidates through it, and verify Priest L20 real P3 progress with a focused native/Forever integration and one justified official result. No Priest rows or parallel Python legality. Preserve Mage L20 P3 PARTIAL **57/155** from the same run and its real weight blockers.
- **Independent of Work1:** no reassignment or takeover of Work2's fork/Forever PRs.

## Work1 follow-up — Druid L60 Balance P7.4, retained under [#131](https://github.com/dosibjrn/forever-sim/issues/131)

- [#41746867119](https://github.com/dosibjrn/forever-sim/actions/runs/41746867119) completed 300.000150s and the frozen 1,000 fights: **FAIL 704.6605/720.9117 DPS (97.75%)**, retained PARTIAL. Paid Balanced winner selection did run; hard-coded `paid_stochastic_*=0` fields are not evidence of missing finalists.
- [PR #758](https://github.com/dosibjrn/forever-sim/pull/758) is an **in-flight receipt-only** correction for real `paid_balanced_finalists` / `paid_balanced_confirmed` counts. Finish its focused CI/handoff without rerunning the unchanged heavy gate; after the higher-value P4 source repair, use actual finalist/refusal evidence for a substantive search change. Maximum remaining M1 credit is only ~**+0.00169 pp**.

## Independent Clean lane

Clean continues safe dead GameIR/P1/P2 retirement under [#357](https://github.com/dosibjrn/forever-sim/issues/357) and [#359](https://github.com/dosibjrn/forever-sim/issues/359). Preserve active P3–P7.5 callers until a real native replacement exists; cleanup earns no gate credit.
