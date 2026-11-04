# WORK PRIORITY — live M1 queue

Refreshed against main `a0950464f4b544e5c5248494a1a05c6a43efb0cc`. Canonical ledger blob: `8a93be655f200dd48206996496373b0c230fb735`.

## Current M1 scoreboard

- **M1 measured: 2.1148%** (`measured_fraction=0.0211477102`).
- **28.169 / 1,332** measured gate-equivalents; **23 PASS / 9 PARTIAL** active-scope gate rows (retired P1/P2 partial rows excluded).
- **0 / 148** certified checkpoints. The measured float is diagnostic coverage, not certification. Only Merge writes `M1_PASSES.tsv`.

## Immediate dependency-ordered queue

### 1. Work1 — Shaman L20 unrestricted P3 native ItemSparse candidates

- New owner task [#847](https://github.com/dosibjrn/forever-sim/issues/847), selected ahead of Priest #817 because the Shaman source-naked policy reached the item-check stage and the first actual failure is a narrow native item-candidate gap.
- The single official light recorder [#41789474594](https://github.com/dosibjrn/forever-sim/actions/runs/41789474594) returned **FAIL**: `P3_NO_LEGAL_ITEMS_IN_CURRENT_DB`. It reached `fast_p3_smoke_for_policy`; no legal Shaman L20 items were found in the ordinary SQLite catalogue. No ledger row or M1 increment. Do not rerun unchanged.
- The selected MythicSim ItemSparse API explicitly supports only Priest/Mage; its Rust class map returns `NATIVE_ITEM_OPTIONS_UNSUPPORTED_CLASS` for Shaman. Forever's `native_item_options_required()` also excludes Shaman, so the failed run did not use native options. The Rust helper's armor/weapon filters are currently Priest/Mage-specific; simply adding Shaman to the class map would not establish correct L20 equipment eligibility.
- **In-flight source implementation:** Work1 opened draft MythicSim fork [PR #11](https://github.com/dosibjrn/mythicsim-forever-engine/pull/11), inspected HEAD `48e4e2eb372ccb5c53ecd442134d580e9fc7e53f` (2026-11-04). Its current six-file diff imports pinned-client `SkillLine` / `SkillRaceClassInfo` Shaman skill eligibility and provenance; **it does not yet connect the projection to `native_item_options`, enable Forever's caller or demonstrate paid P3 scoring**. Fork [Engine checks #41796043597](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41796043597) and [native smoke #41796043555](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41796043555) were in progress at inspection; no PASS inferred. Continue this owned PR, not a competing branch.
- **Next action:** in PR #11 consume the sourced skill projection in the Rust native ItemSparse API, enforce Shaman L20 armor/weapon/relic/slot/class and RequiredLevel eligibility (fail closed on missing source), and test its actual native response. Then pin the tested exact Rust revision and enable the Shaman L20 native caller in Forever without SQLite fallback. Preserve the 44-evaluation P3 cap, source-naked policy and measured-weight predicates. One changed-HEAD no-record P3 run must show nonempty legal native candidates, `real_source_search_evaluated>0`, paid evaluations within 44, and the actual gate result before Merge considers one official recorder.
- Conditional maximum full-PASS gain: `1/1332` = **+0.07508 percentage points**; an eligible PARTIAL earns only its actual measured fraction. No credit is assumed.

### 2. Work2 — Paladin L20 unrestricted P3 source-naked executable baseline

- Existing [issue #845](https://github.com/dosibjrn/forever-sim/issues/845) is now Work2's next independent implementation, **unblocked after official Mage L30 P3 receipt #41793008067**. Work1 remains on Shaman #847, then Priest #817; the two lanes are independent.
- Light recorders [#41787910137](https://github.com/dosibjrn/forever-sim/actions/runs/41787910137) and duplicate [#41787945906](https://github.com/dosibjrn/forever-sim/actions/runs/41787945906) returned **BLOCKED_NO_NAKED_SUCCESS**, `real_source_search_evaluated=0`; no paid scoring and no ledger row.
- Unlike Shaman, the canonical catalogue has **6,849 Paladin class-eligible item IDs**. The first stop is the `source_naked` no-winner path before gear scoring, not missing item candidates.
- **Code evidence on main:** `tools/wf_gate_p3_live.py::run_live` omits backend flags, so `run_source_budgeted_gear` uses its default `policy_search_backend="prefix"`. The same gear runner supports `policy_search_backend="stateful", stateful_search_auto_fallback=True`; `tests/generic/search/test_wf287_source_auto_continuation.py::test_same_auto_continuation_reoptimizes_named_gear_and_talent_root` already exercises that path for Paladin L20 and requires `EVALUATED_BOUNDED` with `AUTO_ONLY_FALLBACK`. Its companion test verifies a real `AutoAttackSwing` timeline event. This is a source-backed, tested alternative—not proof of the P3 root cause.
- **Next action:** reproduce the Paladin L20 P3 `source_naked` stage with the tested stateful + source-auto-fallback configuration under the existing 44-evaluation cap. Wire it into the P3 caller only if a changed-HEAD no-record producer demonstrates a real source-backed winner and paid item/stat scoring. Do not change global defaults, synthesize an action or accept a proxy.
- One changed-HEAD no-record light producer must show `real_source_search_evaluated>0` and actual first paid item/stat assertions (or the exact remaining BLOCKED reason). Merge records once only if eligible measured coverage results. No unchanged retry.
- Conditional full-PASS ceiling: `1/1332` = **+0.07508 percentage points**; near-term gain and cost remain unknown. This is the next independent Work2 task after #831's receipt, while Work1 remains on the separate Rust Shaman/Player work.

### 3. Work1 — Priest L20 unrestricted P4/P5 native level-aware actor

- Existing owner [issue #817](https://github.com/dosibjrn/forever-sim/issues/817); queue this **after #847**. It remains independent of Work2 #818.
- PR #822 already merged native ItemSparse options transport. The post-merge light recorder [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) invoked both gates but returned **BLOCKED**: `P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED`; zero complete paid screens and zero source-action casts.
- Work1's draft MythicSim fork [PR #10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10), exact HEAD `5f564af09192d3f0afe7977e4df78d7cb271b0a7`, now adds a Rust-only `proto.Player.level` field. Omitted/explicit level 60 preserves legacy behavior; explicit level 20 and invalid nonzero levels are refused before constructing a level-60 actor. This removes the silent L60-proxy risk, but **does not yet implement Priest L20 execution** or source-backed L20 base stats/conversions.
- Exact fork Engine checks [#41790253207](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41790253207) are terminal **FAIL**: `cargo fmt -- --check` reports formatting diffs across repository test files, and `cargo test --locked` has **377 passed / 1 failed** at `native_persistent_early_world_kill_clock_boundary` (previously identified as an unchanged fork-main baseline failure). Do not report the new level field as a completed native L20 actor or paid-screen result.
- **Next action after #847:** add MythicSim-owned, source-backed Priest L20 race/class base stats and level-dependent conversions; prepare an actual level-20 native actor; then connect it to the existing paid whole-build evaluator and real 2D/source-action screen. Reconcile the fork checks and run one bounded changed-HEAD no-record Priest P4/P5 producer only when the actual L20 execution path exists. No L60 proxy, guessed stats, Forever GameIR/SQLite fallback or unchanged recorder.
- If both gates eventually produce 2/6 comparable paid-screen behaviors, their conditional combined M1-float opportunity is **+0.05005 pp**. Not earned. Merge dispatches only after real eligible coverage; full PASS still requires the approved 30/300-second searches and 100-mob finalist.


## Completed / no unchanged redispatch

- **Druid L60 Balance P7.4** current-code PASS on both post-#840 heavy runs [#41786536534](https://github.com/dosibjrn/forever-sim/actions/runs/41786536534) and [#41786566461](https://github.com/dosibjrn/forever-sim/actions/runs/41786566461); the canonical receipt remains the single accepted row. No further P7.4 run.
- Hunter L20 P3: `BLOCKED_NO_NAKED_SUCCESS`, zero paid source evaluations; no unchanged retry.
- Mage L20 P3: preserve the 88/224 high-water; no unchanged retry.
- **Mage L30 unrestricted P3:** Work2 PR #831 merged as `7c46654`; official recorder [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067) completed SUCCESS and recorded **PARTIAL 129/224** (57.59%), up from 85/224. The exact no-record result used 44 paid evaluations and scored 85 native top-five items; Spell Power, Intellect and Hit are positive. Gate remains FAIL; no unchanged rerun. The canonical M1 score is now 2.1148%, 28.169/1,332 measured equivalents, 23 PASS / 9 PARTIAL, 0/148 certified.
- Shaman L20 P3: the one light recorder #41789474594 returned `P3_NO_LEGAL_ITEMS_IN_CURRENT_DB`; this is a terminal measured FAIL, not an unmeasured gate or a PASS. Native source-candidate repair is queued as #847; no unchanged retry.

## Operating constraints

- Merge alone dispatches official M1 recorders and writes `M1_PASSES.tsv`; Prio maintains this queue and submits requests on existing owner issues.
- Mage L30 P3 official recorder [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067) is terminal SUCCESS and its PARTIAL 129/224 receipt is in the canonical ledger. Do not duplicate it; Merge alone writes future M1 receipts.
- Prioritize real active P3–P7.5 production progress. No P1/P2 work, retired GameIR search runners, HPS/TPS witness work, MythicSim self-validation, invented positive weights or fabricated M1 rows.
