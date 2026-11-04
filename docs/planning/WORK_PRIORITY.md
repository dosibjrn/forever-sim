# WORK PRIORITY — live M1 queue

Refreshed against main `4ca0163f8c5676d5d1c78324e9c803d4f9a68d71`. Canonical ledger blob: `c45f50ea4fe1aad3d9cf972d24a1981b823600ad`; current `tools/m1_progress.py` blob: `93b3f38c4f663e742d154f7ad90a7b05e0c4defc`.

## Current M1 scoreboard

- **M1 measured: 2.1391% (float=0.0213906002)**; **28.492 / 1,332** measured gate-equivalents; **23 PASS / 10 PARTIAL** active rows. This is partial-inclusive diagnostic coverage, not certification. The script and canonical ledger blobs are unchanged since the latest script output.
- Only Merge runs the trusted recorder and writes `M1_PASSES.tsv`; no other agent edits the ledger.

## 1. Work1 — start now: Shaman L20 unrestricted P3 Spell Power witness ([#859](https://github.com/dosibjrn/forever-sim/issues/859))

- **Baseline:** official recorder [#41800797285](https://github.com/dosibjrn/forever-sim/actions/runs/41800797285) recorded FAIL / PARTIAL **66/204**. The native ItemSparse integration is complete: PR #860 merged as `4ca0163`; exact-head selected-engine run [#41803884068](https://github.com/dosibjrn/forever-sim/actions/runs/41803884068) succeeded and confirmed 1,955 legal native items, 3,075 excluded non-client rows, zero unverified candidates and the unchanged **66/204** result. No additional M1 credit.
- **Action:** query the selected MythicSim Rust engine for the exact PreparedV2 coefficient of the existing source-ranked `lightning_bolt:915`; attach it only to that matching existing direct-damage action, then enable the paid-winner Spell Power witness only when the exact native coefficient was applied.
- **Causal chain:** native coefficient on the existing Lightning Bolt rank → real paid source-policy sensitivity → measured positive Spell Power weight → `pass_count > 66` with the same 204 denominator.
- **Smallest verification:** focused exact-rank/fail-closed adapter regression, then one changed-HEAD no-record Shaman L20 P3 run within the 44-evaluation cap. Require the coefficient application, `MEASURED_POSITIVE_SOURCE_POLICY_WITNESS`, `spell_power > 0`, and increased comparable count. If the engine does not expose the exact rank or the paid witness is not positive, preserve 66/204; Merge records only a real improvement.
- Each added comparable assertion is **+0.000368 percentage points**; maximum remaining room to full P3 PASS is **+0.05079 pp**, not a forecast.
- **Why this is #1:** one existing direct-damage source action and one missing source coefficient are a narrower, higher-probability change than a new L20 actor plus complete paid P4/P5 screens (#817). Paladin P3 (#845) still has zero eligible source evaluations because its actor and weapon are proxies. Mage L30 P3 already has positive Spell Power and multiple other residual axes. Priest P3's current opener is `shadow_word_pain:970` (`PeriodicEffect`), not a drop-in reuse of this direct-damage coefficient path. No unmeasured active gate currently has a comparably evidenced cheap PASS path. PR #860 is merged; #859 is unblocked and not yet in flight.

## 2. Work1 — after #859: Priest L20 unrestricted P4/P5 native actor ([#817](https://github.com/dosibjrn/forever-sim/issues/817))

- The official light run [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) returned BLOCKED at `P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED`: zero complete paid screens and zero source-action casts.
- **Action:** complete MythicSim-owned source-backed Priest L20 base stats and level-dependent conversions; prepare a real L20 actor; connect it to the existing paid whole-build evaluator and real 2D/source-action screen. No L60 proxy, guessed stats or Forever GameIR/SQLite fallback.
- **Verification:** one changed-HEAD no-record light P4/P5 invocation showing a real level-20 actor, complete paid screens and positive source-action casts. Only then hand to Merge for one official recorder. If both gates reach 2/6 comparable behaviors, the conditional combined float is **+0.05005 pp**; not earned. Work2 may reuse this actor only if its native source contract actually supports Paladin.

## Parallel Work2 — Paladin L20 unrestricted P3 source-backed actor and weapon ([#845](https://github.com/dosibjrn/forever-sim/issues/845))

- PR #851 is merged. Merge's official recorder [#41802054768](https://github.com/dosibjrn/forever-sim/actions/runs/41802054768) returned BLOCKED, with 12 source-naked attempts / 11 diagnostic evaluations but **zero eligible source evaluations** because actor stats and the 14-DPS weapon remain proxies. No Paladin ledger row or M1 credit.
- **Action:** establish source-backed Paladin L20 actor and equipped-weapon facts in MythicSim; reuse #817's native level-aware actor if its actual source contract supports Paladin. No proxy credit, synthetic values or unchanged redispatch.

## Operating constraints

- Active gates only: P3–P6 and P7.1–P7.5. No P1/P2, HPS/TPS witnesses, MythicSim self-validation, duplicate unchanged runs, invented weights or fabricated M1 rows.
- Keep tasks dependency-ordered: Work1 #859 → #817; Work2 #845 remains independent; Merge alone records; Clean owns discretionary cleanup.
