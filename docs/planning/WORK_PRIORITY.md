# WORK PRIORITY — live M1 queue

Refreshed against main `28c35d7d843f3bdf81015345e33367f22cc1e525`. Canonical ledger blob: `311bfb194ebd720d1105561d6e032a15359b3273`.

## Current M1 scoreboard

- **M1 measured: 2.1000%** (`measured_fraction=0.0210002413`).
- **27.972 / 1,332** measured gate-equivalents; **23 PASS / 17 PARTIAL** active-scope gate rows.
- **0 / 148** certified checkpoints. The measured float is diagnostic coverage, not certification. Only Merge writes `M1_PASSES.tsv`.

## Immediate dependency-ordered queue

### 1. Work1 — Shaman L20 unrestricted P3 native ItemSparse candidates

- New owner task [#847](https://github.com/dosibjrn/forever-sim/issues/847), selected ahead of Priest #817 because the Shaman source-naked policy reached the item-check stage and the first actual failure is a narrow native item-candidate gap.
- The single official light recorder [#41789474594](https://github.com/dosibjrn/forever-sim/actions/runs/41789474594) returned **FAIL**: `P3_NO_LEGAL_ITEMS_IN_CURRENT_DB`. It reached `fast_p3_smoke_for_policy`; no legal Shaman L20 items were found in the ordinary SQLite catalogue. No ledger row or M1 increment. Do not rerun unchanged.
- The selected MythicSim ItemSparse API explicitly supports only Priest/Mage; its Rust class map returns `NATIVE_ITEM_OPTIONS_UNSUPPORTED_CLASS` for Shaman. Forever's `native_item_options_required()` also excludes Shaman, so the failed run did not use native options. The Rust helper's armor/weapon filters are currently Priest/Mage-specific; simply adding Shaman to the class map would not establish correct L20 equipment eligibility.
- **Next action:** implement source-backed Shaman L20 class/level/armor/weapon/slot eligibility in the MythicSim native ItemSparse API, with explicit refusal if source facts are unavailable; add Rust tests; then enable the Shaman L20 native caller in Forever. Preserve the existing 44-evaluation P3 cap, source-naked policy and measured-weight predicates. One changed-HEAD no-record P3 run must show nonempty legal native candidates, `real_source_search_evaluated>0`, paid evaluations within 44, and the actual gate result before Merge considers one official recorder.
- Conditional maximum full-PASS gain: `1/1332` = **+0.07508 percentage points**; an eligible PARTIAL earns only its actual measured fraction. No credit is assumed.

### 2. Work2 — Mage L30 unrestricted P3 source-witness repair

- Owner [issue #818](https://github.com/dosibjrn/forever-sim/issues/818); active [PR #831](https://github.com/dosibjrn/forever-sim/pull/831), current exact HEAD `132d60a13192365dff0d7c198d05a52d9c4d1b4d`. Its branch is 3 commits ahead / 18 behind current main `28c35d7`; rebase after fixing the current exact-head failures.
- Canonical high-water remains **PARTIAL 85/224** from merged #825. The positive +50 Intellect witness is preserved; no new Spell Power/Spirit witness or M1 increment is demonstrated.
- **Current exact-head validation on `132d60a`:**
  - Repository maintenance [#41790063766](https://github.com/dosibjrn/forever-sim/actions/runs/41790063766): **FAIL, 4 tests**. Two live-P3 regressions fail because `opening_action_ids` is not populated / no caster witness call occurs; the native Mage spell-coefficient test has a missing `query_native_mage_spell_coefficients` import; the exact-rank enrichment test calls keyword-only `build_game_ir_slice` positionally.
  - Selected-engine [#41790063738](https://github.com/dosibjrn/forever-sim/actions/runs/41790063738): **FAIL**. The exact engine builds and Priest/Mage L20 no-record checks pass, but Mage L30 P3 returns `P3_NATIVE_SPELLBOOK_EXECUTION_FAILED:` with empty stderr during native PreparedV2 spellbook execution.
  - Generic source-paid regressions [#41790063781](https://github.com/dosibjrn/forever-sim/actions/runs/41790063781): **SUCCESS**.
- There is no valid exact-head Mage L30 no-record gate result on `132d60a`; the accepted high-water remains 85/224 from #825. Do not treat the generic green suite or an older no-record run as a new gate result.
- **Next action:** fix the four exact maintenance failures; expose the native prepare return code/stdout/stderr and fix the Mage L30 spellbook invocation; rebase onto current main; rerun maintenance, selected-engine and generic source-paid checks on one exact head; then run one no-record Mage L30 P3 producer and compare with 85/224. No merge or official M1 dispatch at an unchanged result.
- The 85/224 high-water leaves at most ~**+0.06033 percentage points** to a full P3 PASS; a single extra comparable assertion is ~+0.000335 pp. Neither is forecast or earned credit. Keep the 44-evaluation cap and do not synthesize weights or use a GameIR workaround.

### 3. Work1 — Priest L20 unrestricted P4/P5 native level-aware actor

- Existing owner [issue #817](https://github.com/dosibjrn/forever-sim/issues/817); queue this **after #847**. It remains independent of Work2 #818.
- PR #822 already merged native ItemSparse options transport. The post-merge light recorder [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) invoked both gates but returned **BLOCKED**: `P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED`; zero complete paid screens and zero source-action casts.
- Work1's draft MythicSim fork [PR #10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10), exact HEAD `5f564af09192d3f0afe7977e4df78d7cb271b0a7`, now adds a Rust-only `proto.Player.level` field. Omitted/explicit level 60 preserves legacy behavior; explicit level 20 and invalid nonzero levels are refused before constructing a level-60 actor. This removes the silent L60-proxy risk, but **does not yet implement Priest L20 execution** or source-backed L20 base stats/conversions.
- Exact fork Engine checks [#41790253207](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41790253207) are terminal **FAIL**: `cargo fmt -- --check` reports formatting diffs across repository test files, and `cargo test --locked` has **377 passed / 1 failed** at `native_persistent_early_world_kill_clock_boundary` (previously identified as an unchanged fork-main baseline failure). Do not report the new level field as a completed native L20 actor or paid-screen result.
- **Next action after #847:** add MythicSim-owned, source-backed Priest L20 race/class base stats and level-dependent conversions; prepare an actual level-20 native actor; then connect it to the existing paid whole-build evaluator and real 2D/source-action screen. Reconcile the fork checks and run one bounded changed-HEAD no-record Priest P4/P5 producer only when the actual L20 execution path exists. No L60 proxy, guessed stats, Forever GameIR/SQLite fallback or unchanged recorder.
- If both gates eventually produce 2/6 comparable paid-screen behaviors, their conditional combined M1-float opportunity is **+0.05005 pp**. Not earned. Merge dispatches only after real eligible coverage; full PASS still requires the approved 30/300-second searches and 100-mob finalist.

### 4. Backlog — Paladin L20 unrestricted P3 source-naked executable baseline

- [Issue #845](https://github.com/dosibjrn/forever-sim/issues/845) records the first reproducible defect. Both light recorders [#41787910137](https://github.com/dosibjrn/forever-sim/actions/runs/41787910137) and duplicate [#41787945906](https://github.com/dosibjrn/forever-sim/actions/runs/41787945906) returned **BLOCKED_NO_NAKED_SUCCESS**, `real_source_search_evaluated=0`. Workflow SUCCESS was not gate PASS; ledger unchanged.
- Work1 takes this after #817, unless later measured evidence reprioritizes. Inspect actual source-naked attempted/blocked reasons and repair only the first proven production deficiency. Do not attribute the failure to a proxy annotation without evidence, invent source mechanics/base stats/weights, or rerun unchanged.

## Completed / no unchanged redispatch

- **Druid L60 Balance P7.4** current-code PASS on both post-#840 heavy runs [#41786536534](https://github.com/dosibjrn/forever-sim/actions/runs/41786536534) and [#41786566461](https://github.com/dosibjrn/forever-sim/actions/runs/41786566461); the canonical receipt remains the single accepted row. No further P7.4 run.
- Hunter L20 P3: `BLOCKED_NO_NAKED_SUCCESS`, zero paid source evaluations; no unchanged retry.
- Mage L20 P3: preserve the 88/224 high-water; no unchanged retry.
- Mage L30 P3: preserve the 85/224 high-water until a changed real producer exceeds it.
- Shaman L20 P3: the one light recorder #41789474594 returned `P3_NO_LEGAL_ITEMS_IN_CURRENT_DB`; this is a terminal measured FAIL, not an unmeasured gate or a PASS. Native source-candidate repair is queued as #847; no unchanged retry.

## Operating constraints

- Merge alone dispatches official M1 recorders and writes `M1_PASSES.tsv`; Prio maintains this queue and submits requests on existing owner issues.
- No M1 recorder was active at this refresh. Never launch a second M1 writer or duplicate a request already ACKed/launched.
- Prioritize real active P3–P7.5 production progress. No P1/P2 work, retired GameIR search runners, HPS/TPS witness work, MythicSim self-validation, invented positive weights or fabricated M1 rows.
