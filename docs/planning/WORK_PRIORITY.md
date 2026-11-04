# FOREVER SIM — active M1 work queue

**Policy:** maximize genuine incremental M1 measured-float per total implementation, validation and compute time. Active gates: P3–P6, P7.1–P7.5 (1,332 pairs). Only **Merge** dispatches the trusted M1 recorder and writes `docs/planning/M1_PASSES.tsv`. P1/P2 and GameIR are retired; no duplicate Python Warcraft legality or HPS/TPS side quests.

**Verified current ledger:** **M1 measured: 1.6840% (float=0.0168400253)**; **19/1,332** active PASS gates, **0/148** certified checkpoints. Latest recorder [#41755971300](https://github.com/dosibjrn/forever-sim/actions/runs/41755971300) published Druid L60 unrestricted P5 PASS as [`136c5186`](https://github.com/dosibjrn/forever-sim/commit/136c51862260c9d8ab5e27e15550104a5a71a16c). Druid L40 P5 [#766](https://github.com/dosibjrn/forever-sim/issues/766) and L60 P5 [#767](https://github.com/dosibjrn/forever-sim/issues/767) are **closed/PASS**. Do not repeat. Partial-inclusive M1 is not checkpoint certification.

## #1 — Merge: one full Druid L30 unrestricted P5 — [#771](https://github.com/dosibjrn/forever-sim/issues/771)

- **Measured baseline:** `druid:30:unrestricted:P5` is **PARTIAL 3/35**, only a bounded diagnostic [#41460804275](https://github.com/dosibjrn/forever-sim/actions/runs/41460804275); **no full P5** has been executed. P4 genuinely **PASSed** [#41753303533](https://github.com/dosibjrn/forever-sim/actions/runs/41753303533): 29.832s, N30=385, complete 100/100 finalist, engine `gsim-0.11.48.289`, source `400e032142c7097d8b129a75133ff572369671ec6db8e98b9227800d014e9161`.
- **Best next action:** after checking live/recent Actions and ledger for an identical run, Merge dispatches **once** `/m1-run --heavy druid:30:unrestricted:P5` on fresh main. Independent cold 300s, same source/legal space/objective, N300 >= 770 (2×N30), actual talent-unlocked action execution and one complete 100-mob finalist. Producer decides verdict; only Merge records it. Do not overlap heavy runs.
- **Expected unearned marginal credit:** `(1-3/35)/1332 = 0.0006864007` fraction (**+0.06864 percentage points**). Three already accepted Druid unrestricted P5 full PASSes at L20/L40/L60 support the path; they do not prove L30.

## #2 — Merge, only after #771: one Druid L20 unrestricted P6 — [#774](https://github.com/dosibjrn/forever-sim/issues/774)

- **Measured baseline:** `druid:20:unrestricted:P6` **not yet measured**. P4 [#41750754719](https://github.com/dosibjrn/forever-sim/actions/runs/41750754719) and P5 [#41752806993](https://github.com/dosibjrn/forever-sim/actions/runs/41752806993) genuinely PASSed on the same engine/source; their separate finalist times were T30=10.37065 and T300=10.54084 s/mob, satisfying the numeric 1% inequality. These historical winners **do not constitute P6 acceptance**.
- **Action:** after #771 terminal, re-rank and check duplicate/in-flight Actions. If still best, Merge dispatches **once** `/m1-run --heavy druid:20:unrestricted:P6` via the full-source P6 production route: new independent cold 30s/300s searches, two real complete 100-mob winner replays, same source/engine/scenario and `T30 <= 1.01 × T300`. The bounded 4s/6s diagnostic is not acceptance.
- **Expected unearned credit:** new PASS could add `1/1332 = 0.0007507508` fraction (**+0.07508 pp**); requires at least 330s searches plus replays, so not a free/cheap replay. Re-rank if #771 or other new evidence changes the priority.

## #3 — Work2: Priest L20 unrestricted P3 native legal item options — [#754](https://github.com/dosibjrn/forever-sim/issues/754)

- **Observed FAIL:** [#41747651321](https://github.com/dosibjrn/forever-sim/actions/runs/41747651321) `P3_NO_LEGAL_ITEMS_IN_CURRENT_DB`; no Priest P3 row. Mage L20 P3 retains PARTIAL 57/155. Native fork [PR #5](https://github.com/dosibjrn/mythicsim-forever-engine/pull/5) exposed options but not supported required levels; static checks alone do not prove level-legal data.
- **Next:** Work2 obtains real Rust-owned required-level item data (not ilvl inference), filters legal options in native, tests exact fork HEAD, pins it, wires the P3 candidate source without SQLite/Python legality, and requests one justified producer measurement. This can unlock multiple P3 gates; no PASS assumed.

## #4 — Work1: repair confirmed Druid L60 Balance P7.4 candidate-source FAIL — [#131](https://github.com/dosibjrn/forever-sim/issues/131)

- **New production FAIL:** post-merge official [#41757111345](https://github.com/dosibjrn/forever-sim/actions/runs/41757111345) stopped before the 300s search: `P7_4_PINNED_RUST_ITEM_OPTIONS_FAILED:ValueError:No pinned Rust item options for slot=relic, type=ItemTypeRanged`. Source-option PRs [#765](https://github.com/dosibjrn/forever-sim/pull/765) and [#769](https://github.com/dosibjrn/forever-sim/pull/769) are already **merged**. No new M1 credit; prior PARTIAL 704.6605/720.9117 DPS remains (max **+0.00169 pp**).
- **Next:** Work1 reproduces/fixes the concrete relic/ranged candidate-pool mapping on the existing production path, with focused regression and affected CI. Do not invent Rust items or bypass native legality. Merge measures P7.4 once **only after** a tested code fix; no unchanged heavy rerun. This repair is independent of Merge's higher-float P5/P6 work.

**Dispatch discipline:** no overlapping heavy measurements; check current ledger and live/recent Actions before each. No agent except Merge records PASS/PARTIAL. Keep this queue current-only; closed tasks stay in their issues, not as active slots.
