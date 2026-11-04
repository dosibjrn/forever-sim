# WORK PRIORITY — live M1 queue

Refreshed against main `1648dd5996d41f68635922651634f4503f908f8b`. Canonical ledger blob: `311bfb194ebd720d1105561d6e032a15359b3273`.

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

- Owner [issue #818](https://github.com/dosibjrn/forever-sim/issues/818); current [PR #831](https://github.com/dosibjrn/forever-sim/pull/831), latest checked head `5597453fc47efcb732c6d8d7c022c7e943844e82`, based on main `384e584` (behind current main `1648dd5`, which includes Clean PR #846 plus subsequent Prio queue commits; rebase after the final Work2 head stabilizes).
- Canonical high-water remains **PARTIAL 85/224** from merged #825. The positive +50 Intellect witness is preserved; no new Spell Power witness or M1 increment is demonstrated.
- Prior exact heads exposed two real classes of regression: (a) the fallback fixture expected a third source-policy stat probe even though the source baseline failed and the paid budget is two; the valid production sequence is source-policy baseline then paid-winner perturbation, both with the observed `mage:fireball` opening; (b) subsequent native spellbook work exposed a missing witness call/opening prefix, missing `query_native_mage_spell_coefficients` import, positional use of keyword-only `build_game_ir_slice`, and an empty-stderr native `prepare` failure. Do not increase the 44-evaluation cap, invent a baseline or hide native return/stdout/stderr.
- Latest checked head `5597453`: selected-Rust verification [#41790750138](https://github.com/dosibjrn/forever-sim/actions/runs/41790750138) **SUCCESS**; generic source-paid [#41790750100](https://github.com/dosibjrn/forever-sim/actions/runs/41790750100) **in progress**; exact-head maintenance [#41790750112](https://github.com/dosibjrn/forever-sim/actions/runs/41790750112) **FAIL: 3 failed, 392 passed**. The failures are two test references to `query_native_mage_spell_coefficients` missing from the test module's namespace and one positional call to keyword-only `build_game_ir_slice`; fix the imports and use explicit keyword arguments. A previous head also exposed an empty-stderr `P3_NATIVE_SPELLBOOK_EXECUTION_FAILED`; if it recurs, surface native prepare return code/stdout/stderr.
- The PR body still names an older head and the base `384e584` is behind current main `1648dd5` (Clean PR #846 plus Prio queue commits). After fixing these exact-head failures, refresh the body, rebase onto current main, rerun maintenance + selected-Rust + generic source-paid on one exact head, then run one no-record Mage L30 P3 producer and compare against 85/224. No merge or official M1 dispatch at an unchanged result. No synthetic weights or GameIR workaround.

### 3. Work1 — Priest L20 unrestricted P4/P5 native level-aware actor

- Existing owner [issue #817](https://github.com/dosibjrn/forever-sim/issues/817), now sharpened to the exact selected-Rust capability gap. Queue this **after #847**; it remains independent of Work2 #818.
- PR #822 already merged native ItemSparse options transport. The post-merge light recorder [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) invoked both gates but returned **BLOCKED**: `P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED`; zero complete paid screens and zero source-action casts.
- Exact selected fork audit ([evidence](https://github.com/dosibjrn/forever-sim/issues/817#issuecomment-6623513584)) shows `proto.Player` has no level field, native `new_character` sets level 60 unconditionally, and the selected `go-tables.json` base-stat rows have no level dimension. A request-side `level:20` or CLI flag alone is not sufficient.
- **Next action after #847:** implement a MythicSim-owned level-aware Player contract, requested-level actor preparation and source-backed L20 base stats/conversions; connect it to the existing paid whole-build evaluator and real 2D/source-action screen. Rust tests first, then one exact-HEAD no-record Priest L20 P4/P5 producer showing actor level 20, COMPLETE paid screens and positive source-action casts. No level-60 proxy, guessed stats, Forever GameIR/SQLite fallback or new gate.
- If both gates eventually produce 2/6 comparable paid-screen behaviors, their conditional combined partial-inclusive M1 opportunity is **+0.05005 pp**. Not earned. Merge dispatches only after real eligible coverage; full PASS still requires the approved 30/300-second searches and 100-mob finalist.

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
