# WORK PRIORITY — live M1 queue

Refreshed against main `494ad2bfe675b96a5aabfd9f22f912b8aaf9ec1e`. Canonical ledger blob: `ab3e8ad0faa686e8782c236b45177e0042fb6eb3`; current `tools/m1_progress.py` blob: `93b3f38c4f663e742d154f7ad90a7b05e0c4defc`.

## Current M1 scoreboard

- **M1 measured: 2.1490% (float=0.0214899642)**; **28.625 / 1,332** measured gate-equivalents; **23 PASS / 10 PARTIAL** active rows. Partial-inclusive diagnostic coverage, not certification; certified checkpoints remain 0/148.
- Shaman L20 unrestricted P3 is now officially **PARTIAL 93/204**, replacing 66/204, from the single Merge recorder [#41808193281](https://github.com/dosibjrn/forever-sim/actions/runs/41808193281). This is +27 comparable assertions, not a P3 PASS.
- Only Merge runs the trusted recorder and writes `M1_PASSES.tsv`.

## 1. Work1 — next: Priest L20 unrestricted P4/P5 native actor ([#817](https://github.com/dosibjrn/forever-sim/issues/817))

- **Baseline:** official light run [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) invoked both gates and returned **BLOCKED** at `P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED`: zero complete paid screens and zero source-action casts. No Priest L20 P4/P5 ledger rows.
- **Action:** complete the MythicSim-owned level-20 Priest actor preparation with source-backed base stats/conversions, then connect that actual actor to the existing paid whole-build evaluator and real 2D/source-action screen. The open fork PR #10 only adds an explicit player-level request field and refuses L20; it is not a level-20 actor. Do not treat Work2's separate Paladin `player-context` P3 path as a prepared combat actor.
- **Causal chain:** real native Priest L20 actor → complete paid whole-build screens and positive source-action casts → measured comparable P4/P5 coverage. If each gate reaches 2/6 actual paid-screen behaviors, the conditional combined M1 gain is **+0.05005 pp**; not earned and not a full gate PASS.
- **Smallest verification:** focused Forever-owned request/refusal transport regressions, then one changed-HEAD no-record light P4/P5 production invocation reporting actual actor level 20, `screen_status=COMPLETE`, paid whole-build counts and positive `source_action_counts`. Only after that, hand to Merge for one official light recorder. No L60 proxy, Python/GameIR/SQLite fallback, separate MythicSim rules audit or heavy 30/300-second search before the real path exists.
- **Why #1:** this is the best unstarted independent Work1 lane after Shaman #859's completed implementation/official recording. It shares one native actor across two currently unmeasured gates. The remaining P3 candidates have no equally narrow, source-backed next defect; Druid P6 rows are already saturated at 200/200.

## Parallel Work2 — Paladin L20 unrestricted P3 ([#845](https://github.com/dosibjrn/forever-sim/issues/845))

- **Baseline:** official recorder [#41802054768](https://github.com/dosibjrn/forever-sim/actions/runs/41802054768) returned **BLOCKED**: 12 source-naked attempts / 11 diagnostic evaluations, but **zero eligible source evaluations** because actor stats and the 14-DPS weapon were scenario proxies.
- **Current work:** Forever draft PR [#865](https://github.com/dosibjrn/forever-sim/pull/865) transports the native player-context response into the P3 caller, but does not yet provide a full PreparedV2 actor or native Paladin item-options. MythicSim draft PR [#12](https://github.com/dosibjrn/mythicsim-forever-engine/pull/12) exposes a source-backed Paladin L20 P3 context, not a full combat actor; its focused context test passed, but broad engine checks are not green. The separate Paladin equipment-source import run [#41808322587](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41808322587) failed at deterministic source projection.
- **Action:** finish the source-backed native Paladin P3 player context and legal item-options capability on the fork, promote only a tested exact SHA, then run one changed-HEAD no-record Paladin P3 producer. Require actual eligible source evaluations and measured P3 improvement before asking Merge for the single official recorder. Keep the 44-evaluation cap; no proxy credit, guessed stats or invented legality.
- This remains Work2's independent in-flight task; do not take its branch or duplicate its native work.

## Alternatives / sequencing

- Mage L30 P3 issue [#818](https://github.com/dosibjrn/forever-sim/issues/818) is no longer at its old 44/224 baseline: the canonical row is **129/224** from [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067). Positive Spell Power/Intellect are already measured; remaining stat/source axes have no currently demonstrated single cheap repair. Do not rerun unchanged.
- Druid L30/L40 P6 are already 200/200 partials; Druid L60 Balance P7.4 has a much smaller remaining M1 opportunity and requires the expensive approved holdout. Neither outranks the two active implementation lanes.
- Active gates only: P3–P6 and P7.1–P7.5. No P1/P2, HPS/TPS witnesses, MythicSim self-validation, duplicate unchanged runs, invented weights or fabricated M1 rows.
- Keep the queue current-only and dependency ordered. Merge alone records; Clean owns discretionary cleanup.
