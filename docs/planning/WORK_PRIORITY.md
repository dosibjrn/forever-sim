# FOREVER SIM — active M1 work queue

**Policy:** maximize credible incremental M1 measured-float gain per total implementation, validation and compute time. Active gates are P3–P6 and P7.1–P7.5 (1,332 pairs). Only Merge dispatches trusted M1 measurements and writes `M1_PASSES.tsv`. P1/P2 and GameIR are retired; no parallel Warcraft legality or unrelated HPS/TPS work.

**Latest main scoreboard:** M1 measured: **1.5356% (float=0.0153563988)**; **17/1,332 accepted PASS gates; 0/148 certified checkpoints**. Partial-inclusive diagnostic, not checkpoint certification. Selection baseline was `main@94b6e851ca86416ccef56a9ee3aae443d01d5be0`; canonical ledger `cb9c300d5dd2862683584b0c25e1d65ff04a6fd7`. The two latest genuine PASSes are Druid L20 P5 [#41752806993](https://github.com/dosibjrn/forever-sim/actions/runs/41752806993) and Druid L30 P4 [#41753303533](https://github.com/dosibjrn/forever-sim/actions/runs/41753303533); their tasks [#761](https://github.com/dosibjrn/forever-sim/issues/761) and [#753](https://github.com/dosibjrn/forever-sim/issues/753) are closed. Do not repeat either run.

## #1 — Merge: one full Druid L40 unrestricted P5 measurement — [#766](https://github.com/dosibjrn/forever-sim/issues/766)

- **Baseline:** `druid:40:unrestricted:P5` remains PARTIAL **1/42** from bounded [#41505335059](https://github.com/dosibjrn/forever-sim/actions/runs/41505335059); only 10 paid builds/screens, with the full 300s search and 100-mob finalist explicitly not executed.
- **Credible pass path:** same checkpoint P4 PASS [#41744549169](https://github.com/dosibjrn/forever-sim/actions/runs/41744549169): 29.792s cold search, **N30=213** unique paid full builds/screens, complete 100/100-mob finalist, runtime `gsim-0.11.48.289`, source revision `b8631d2091d18fc4630248f76992c70f42a2790340026f00c253c7b31434eaf0`.
- **Action:** Merge rechecks for an identical live/recent run, then dispatches exactly once on current main: `/m1-run --heavy druid:40:unrestricted:P5`. Keep it cold/independent on the same objective/source/legal space. P5 requires 300 actual wall seconds, **N300 ≥ 426** (2×N30), and one complete 100-mob finalist. Only the real producer decides PASS/FAIL/PARTIAL/BLOCKED.
- **Why #1:** the existing PARTIAL leaves at most `(1-1/42)/1332 = 0.0007328757` measured fraction (**+0.07329 percentage points**, unearned). This exceeds Druid L30 P5's +0.06864 pp, at the same 300s budget but with a lower breadth threshold (426 vs 770). Druid L20 P5 also just passed on the same class/spec/runtime path: 299.108s, N30=421, N300=2,990 and complete 100-mob finalist. No PASS is presumed.

## #2 — Work2: native Priest L20 unrestricted P3 legal item options — [#754](https://github.com/dosibjrn/forever-sim/issues/754)

- **Baseline:** official [#41747651321](https://github.com/dosibjrn/forever-sim/actions/runs/41747651321) returned `P3_NO_LEGAL_ITEMS_IN_CURRENT_DB`; no Priest P3 PARTIAL/PASS. Preserve Mage L20 P3 PARTIAL 57/155.
- **Current implementation evidence:** native fork PR [#5](https://github.com/dosibjrn/mythicsim-forever-engine/pull/5), exact HEAD `070f64f22afe9bff36fb32a1634450fdc5b2b709`, exposes item options but returns `required_level: null` / `required_level_supported=false`. Static source-contract checks are 8/8; Rust tests/CI have not run. This is not level-legal P3 data.
- **Next:** source an actual native required-level field (never infer it from ilvl), filter options in Rust, run exact-head Rust tests, pin the tested fork, wire the fail-closed native response into Forever P3, then request one justified Priest/Mage P3 production measurement. No SQLite/Python legality workaround and no PASS claim.

## #3 — Work1: Druid L60 Balance P7.4 candidate-source improvement — [#131](https://github.com/dosibjrn/forever-sim/issues/131), [PR #765](https://github.com/dosibjrn/forever-sim/pull/765)

- **Baseline:** official [#41746867119](https://github.com/dosibjrn/forever-sim/actions/runs/41746867119) remains PARTIAL **704.6605/720.9117 DPS (97.75%)**; maximum remaining M1 credit is only **+0.00169 pp**.
- **In-flight change:** PR #765 replaces SQLite candidate proposals with pinned native Rust gear-options. It depends on MythicSim engine PR [#3](https://github.com/dosibjrn/mythicsim-forever-engine/pull/3); exact-head regressions are running. Preserve this owned branch; no unchanged 300s/1,000-fight rerun. Merge measures once only after the candidate-source change is integrated and exact-head validation passes.

**Next measurement candidate after #766:** Druid L30 unrestricted P5 remains PARTIAL 3/35; its P4 now PASSes with N30=385 in [#41753303533](https://github.com/dosibjrn/forever-sim/actions/runs/41753303533). A full P5 could add at most +0.06864 pp and needs N300 ≥ 770. Re-rank it against the then-current ledger after #766; do not dispatch concurrently or assume PASS.
