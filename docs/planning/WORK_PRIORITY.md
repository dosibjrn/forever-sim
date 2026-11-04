# WORK PRIORITY — live M1 queue

Refreshed against main `7c46654e0a228af8e4ad0fe3cd5bebf5428464d9`. Canonical ledger blob: `311bfb194ebd720d1105561d6e032a15359b3273`.

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

### 2. Merge — Mage L30 unrestricted P3 official receipt (Work2 implementation merged)

- Work2's [issue #818](https://github.com/dosibjrn/forever-sim/issues/818) implementation [PR #831](https://github.com/dosibjrn/forever-sim/pull/831) is merged on main as `7c46654e0a228af8e4ad0fe3cd5bebf5428464d9`.
- The merged exact-head producer [#41792443131](https://github.com/dosibjrn/forever-sim/actions/runs/41792443131) returned actual Mage L30 unrestricted P3 **FAIL / PARTIAL 129/224 (57.59%)**, up from the accepted 85/224: **+44 comparable assertions**, 44 real paid evaluations and 85 native top-five items scored. Exact-head maintenance [#41792443120](https://github.com/dosibjrn/forever-sim/actions/runs/41792443120) passed (395); generic source-paid [#41792443139](https://github.com/dosibjrn/forever-sim/actions/runs/41792443139) passed (317).
- The source-backed native PreparedV2 receipt is `MYTHICSIM_RUST_PREPARED_V2_PLAYER_SPELLS`, engine revision `a667dce8492bd9fb94269a9f864289cb74006775`; applied coefficients are `frostbolt:8406 = 0.8140000104904175` and `fireball:8401 = 1.0`. Measured Spell Power is positive at `0.1498765432 s/mob/unit`; Intellect remains positive at `0.2298024691 s/mob/unit`. The 44-evaluation cap is unchanged.
- Remaining P3 FAIL reasons: missing Stamina/Strength weights, 2,239 unknown-required-level candidates, nine unmapped native axes, and nonpositive Agility/Attack Power/MP5/Spirit. This is a real partial improvement, **not P3 PASS**.
- Merge-owned official recorder [#41793008067](https://github.com/dosibjrn/forever-sim/actions/runs/41793008067) is **in progress** on main `7c46654`. The last canonical ledger read is still blob `311bfb194ebd720d1105561d6e032a15359b3273` with Mage L30 P3 at 85/224; do not assume the score has changed until the recorder is terminal. Merge alone writes the TSV; **do not dispatch a second recorder**.
- After that official receipt, Work2's next independent implementation is Paladin L20 P3 [#845](https://github.com/dosibjrn/forever-sim/issues/845). No unchanged Mage L30 producer rerun.
### 3. Work1 — Priest L20 unrestricted P4/P5 native level-aware actor

- Existing owner [issue #817](https://github.com/dosibjrn/forever-sim/issues/817); queue this **after #847**. It remains independent of Work2 #818.
- PR #822 already merged native ItemSparse options transport. The post-merge light recorder [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) invoked both gates but returned **BLOCKED**: `P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED`; zero complete paid screens and zero source-action casts.
- Work1's draft MythicSim fork [PR #10](https://github.com/dosibjrn/mythicsim-forever-engine/pull/10), exact HEAD `5f564af09192d3f0afe7977e4df78d7cb271b0a7`, now adds a Rust-only `proto.Player.level` field. Omitted/explicit level 60 preserves legacy behavior; explicit level 20 and invalid nonzero levels are refused before constructing a level-60 actor. This removes the silent L60-proxy risk, but **does not yet implement Priest L20 execution** or source-backed L20 base stats/conversions.
- Exact fork Engine checks [#41790253207](https://github.com/dosibjrn/mythicsim-forever-engine/actions/runs/41790253207) are terminal **FAIL**: `cargo fmt -- --check` reports formatting diffs across repository test files, and `cargo test --locked` has **377 passed / 1 failed** at `native_persistent_early_world_kill_clock_boundary` (previously identified as an unchanged fork-main baseline failure). Do not report the new level field as a completed native L20 actor or paid-screen result.
- **Next action after #847:** add MythicSim-owned, source-backed Priest L20 race/class base stats and level-dependent conversions; prepare an actual level-20 native actor; then connect it to the existing paid whole-build evaluator and real 2D/source-action screen. Reconcile the fork checks and run one bounded changed-HEAD no-record Priest P4/P5 producer only when the actual L20 execution path exists. No L60 proxy, guessed stats, Forever GameIR/SQLite fallback or unchanged recorder.
- If both gates eventually produce 2/6 comparable paid-screen behaviors, their conditional combined M1-float opportunity is **+0.05005 pp**. Not earned. Merge dispatches only after real eligible coverage; full PASS still requires the approved 30/300-second searches and 100-mob finalist.

### 4. Work2 — Paladin L20 unrestricted P3 source-naked executable baseline

- Existing [issue #845](https://github.com/dosibjrn/forever-sim/issues/845) has been reallocated to **Work2 after #831's official Mage L30 P3 receipt**. Do not start concurrently with #831 because both touch the P3 source-budgeted path. Work1 remains on Shaman #847, then Priest #817.
- Light recorders [#41787910137](https://github.com/dosibjrn/forever-sim/actions/runs/41787910137) and duplicate [#41787945906](https://github.com/dosibjrn/forever-sim/actions/runs/41787945906) returned **BLOCKED_NO_NAKED_SUCCESS**, `real_source_search_evaluated=0`; no paid scoring and no ledger row.
- Unlike Shaman, the canonical catalogue has **6,849 Paladin class-eligible item IDs**. The first stop is the `source_naked` no-winner path before gear scoring, not missing item candidates.
- **Next action:** inspect actual `source_naked` attempted/blocked reasons and selected Paladin L20 actions/policy. Check whether the existing source-authorized `include_auto_fallback` path is the missing repeatable filler, but treat it as a candidate—not a proven root cause. Repair only the first demonstrated production deficiency; do not accept proxy stats or invent mechanics.
- One changed-HEAD no-record light producer must show `real_source_search_evaluated>0` and actual first paid item/stat assertions (or the exact remaining BLOCKED reason). Merge records once only if eligible measured coverage results. No unchanged retry.
- Conditional full-PASS ceiling: `1/1332` = **+0.07508 percentage points**; near-term gain and cost remain unknown. This is the next independent Work2 task after #831's receipt, while Work1 remains on the separate Rust Shaman/Player work.
## Completed / no unchanged redispatch

- **Druid L60 Balance P7.4** current-code PASS on both post-#840 heavy runs [#41786536534](https://github.com/dosibjrn/forever-sim/actions/runs/41786536534) and [#41786566461](https://github.com/dosibjrn/forever-sim/actions/runs/41786566461); the canonical receipt remains the single accepted row. No further P7.4 run.
- Hunter L20 P3: `BLOCKED_NO_NAKED_SUCCESS`, zero paid source evaluations; no unchanged retry.
- Mage L20 P3: preserve the 88/224 high-water; no unchanged retry.
- Mage L30 P3: canonical ledger last read remains 85/224; merged no-record producer measured 129/224. Official recorder #41793008067 is in progress; no duplicate or assumed credit.
- Shaman L20 P3: the one light recorder #41789474594 returned `P3_NO_LEGAL_ITEMS_IN_CURRENT_DB`; this is a terminal measured FAIL, not an unmeasured gate or a PASS. Native source-candidate repair is queued as #847; no unchanged retry.

## Operating constraints

- Merge alone dispatches official M1 recorders and writes `M1_PASSES.tsv`; Prio maintains this queue and submits requests on existing owner issues.
- One official M1 recorder is active: #41793008067 for the merged Mage L30 P3 change. Never launch a second M1 writer or duplicate a request already ACKed/launched.
- Prioritize real active P3–P7.5 production progress. No P1/P2 work, retired GameIR search runners, HPS/TPS witness work, MythicSim self-validation, invented positive weights or fabricated M1 rows.
