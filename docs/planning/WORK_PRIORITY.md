# WORK PRIORITY — live M1 queue

Refreshed against main `494ad2bfe675b96a5aabfd9f22f912b8aaf9ec1e`. Canonical ledger blob: `ab3e8ad0faa686e8782c236b45177e0042fb6eb3`; current `tools/m1_progress.py` blob: `93b3f38c4f663e742d154f7ad90a7b05e0c4defc`.

## Current M1 scoreboard

- **M1 measured: 2.1391% (float=0.0213906002)**; **28.492 / 1,332** measured gate-equivalents; **23 PASS / 10 PARTIAL** active rows. This is partial-inclusive diagnostic coverage, not certification. The canonical ledger and scoreboard script blobs are unchanged. Only Merge writes `M1_PASSES.tsv`.

## 1. Merge — Shaman L20 unrestricted P3 official receipt in progress (#859 / PR #862)

- PR #862 merged as `d0185e1ad7e0b3ceb6ead1133af846ff06db71df`. Merge's single official recorder [#41808193281](https://github.com/dosibjrn/forever-sim/actions/runs/41808193281) is running on the merged main SHA; the pre-run canonical row remains PARTIAL **66/204**. Do not dispatch a duplicate.
- The merged change's exact-head no-record selected-engine run [#41807584155](https://github.com/dosibjrn/forever-sim/actions/runs/41807584155) returned actual P3 **FAIL 93/204 (45.59%)**, 35 paid evaluations, **+27 comparable assertions** versus 66/204. Exact native untagged `lightning_bolt:915` coefficient `0.7139999866485596`; explicit `MEASURED_POSITIVE_SOURCE_POLICY_WITNESS` for Spell Power, weight `0.03283717129264803`, two paid evaluations. Native ItemSparse: 1,955 legal items, 3,075 excluded non-client rows, zero unverified.
- Exact-head maintenance [#41807584069](https://github.com/dosibjrn/forever-sim/actions/runs/41807584069): **SUCCESS, 514 passed**. Generic source-paid [#41807584164](https://github.com/dosibjrn/forever-sim/actions/runs/41807584164): **SUCCESS, 317 passed**.
- **Next:** wait for [#41808193281](https://github.com/dosibjrn/forever-sim/actions/runs/41808193281) to become terminal and verify the trusted ledger publication. If the official result preserves 93/204, the conditional high-water improvement is +27/204/1,332 = **+0.009936 pp**. Not earned until the ledger changes; P3 remains FAIL, not PASS. Do not rerun unchanged code.
- M1 affected gate: `shaman:20:unrestricted:P3`.

## 2. Work1 — start next: Priest L20 unrestricted P4/P5 (#817)

- Shaman PR #862 is now merged; its official recorder is running independently. Work1's next implementation can start without waiting for the recorder.
- Official Priest light run [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) returned **BLOCKED** for both gates at `P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED`: zero complete paid screens and zero source-action casts; no ledger rows.
- **Action:** finish MythicSim-owned source-backed Priest L20 actor preparation and connect the actual level-20 actor to the existing paid whole-build evaluator and real 2D/source-action screen. No L60 proxy, guessed stats, Forever GameIR/SQLite fallback or separate MythicSim rules audit.
- **Smallest verification:** one changed-HEAD no-record light P4/P5 invocation showing the actual L20 actor, complete paid screens and positive source-action casts. Only then hand to Merge for an official recorder. Two genuine 2/6 slices would be conditional **+0.05005 pp combined**, not earned.
- **Why #817 next:** Hunter L20 P3 #827 was already attempted and closed after zero-source-evaluation BLOCKED results; Druid L40 and L60 unrestricted P3/P4/P5 are already PASS; Mage L30 P5 already has a PARTIAL row. No unassigned unmeasured gate has a better evidenced low-cost PASS path. #817 is the clearest independent two-gate implementation opportunity.

## 3. Work2 — independent Paladin L20 unrestricted P3 (#845 / PR #865)

- Official recorder [#41802054768](https://github.com/dosibjrn/forever-sim/actions/runs/41802054768) returned **BLOCKED**, with zero eligible source evaluations because actor stats and weapon were proxies; no Paladin ledger row or M1 credit.
- Work2's draft PR #865 at `ed2b72cb416ba33ec5fd718902a936098c693336` adds selected-native player-context transport. Exact parent checks: maintenance [#41807326163](https://github.com/dosibjrn/forever-sim/actions/runs/41807326163) **512 passed**, selected-engine [#41807325995](https://github.com/dosibjrn/forever-sim/actions/runs/41807325995) **SUCCESS**, generic source-paid [#41807326633](https://github.com/dosibjrn/forever-sim/actions/runs/41807326633) **317 passed**. This is a partial context transport, not yet a complete PreparedV2 actor or a P3 result; native fork PR #12 is still draft.
- **Action:** complete the native source-backed Paladin L20 actor/equipped-weapon context and legal item-options path; then one changed-HEAD no-record P3 run. Keep the 44-evaluation cap. No official recorder until real source evaluations are eligible. Work2 owns this lane; do not duplicate #817's actor work or assume cross-class reuse without native support.

## Operating constraints

- Active gates only: P3–P6 and P7.1–P7.5. No P1/P2, HPS/TPS, MythicSim self-validation, proxy credit, duplicate unchanged runs, invented weights or manual ledger edits. Merge alone records; Clean owns discretionary cleanup.
