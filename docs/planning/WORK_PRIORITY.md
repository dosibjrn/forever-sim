# WORK PRIORITY — live M1 queue

Refreshed against main `384e584089dac13d6101b3ea7e67d53de83332b0`. Canonical ledger blob: `311bfb194ebd720d1105561d6e032a15359b3273`.

## Current M1 scoreboard

- **M1 measured: 2.1000%** (`measured_fraction=0.0210002413`).
- **27.972 / 1,332** measured gate-equivalents; **23 PASS / 17 PARTIAL** active-scope gate rows.
- **0 / 148** certified checkpoints. The measured float is diagnostic coverage, not certification. Only Merge writes `M1_PASSES.tsv`.

## Immediate dependency-ordered queue

### 1. Merge — Shaman L20 unrestricted P3 (single light measurement)

- **Gate:** `shaman:20:unrestricted:P3`; canonical ledger has **no row** (not yet measured, not PASS/FAIL).
- Existing `registry.py` Shaman source provider declares L10–L20 coverage; `wf_gate_p3_live.py` uses the real bounded **44-evaluation** paid scorer and selected native item-options client. This is a credible cheap first measurement, **not** a promise that the source-naked policy or item context succeeds.
- **Executable dispatch:** [one `M1-DISPATCH-REQUEST` on owner issue #131](https://github.com/dosibjrn/forever-sim/issues/131#issuecomment-6624706584). Merge checks no ACK/active writer, then launches **exactly one** light production recorder on fresh main. If BLOCKED, preserve the actual reason and do not repeat unchanged.
- Conditional maximum full-PASS gain: `1/1332` = **+0.07508 percentage points**. Any eligible PARTIAL earns only the actual measured fraction. No gain is credited before a trusted recorder.

### 2. Work1 — Priest L20 unrestricted P4/P5: unpark real native gear-options path

- Existing owner [issue #817](https://github.com/dosibjrn/forever-sim/issues/817). Both gates were **BLOCKED** in [#41775113953](https://github.com/dosibjrn/forever-sim/actions/runs/41775113953): `SOURCE_COLD_SEARCH_IR_OR_GEAR_ROLE_UNAVAILABLE`; no ledger rows.
- Current `available_gear_roles('priest')` supplies no role. Remove that **live pre-veto** by using source-authorized candidate options from the selected MythicSim native boundary in the real paid cold-search path; no invented Python gear role, duplicate GameIR or new gate. The existing native item-options transport is available. Only change Rust for a specifically reproduced missing active capability.
- **Unpark now:** this two-gate repair is independent of Work2's Mage P3 branch; waiting for Mage to finish has no demonstrated technical dependency. Smallest proof: focused native request/refusal tests plus **one changed-HEAD no-record bounded** Priest L20 P4/P5 production invocation with actual paid screen/source-action counts. Merge records only if eligible progress is demonstrated.
- Conditional `2/6` measured for each would yield **+0.05005 percentage points** combined. Full PASS still requires the approved 30/300s and 100-mob criteria; no automatic PASS.

### 3. Work2 — Mage L30 unrestricted P3: repair real paid stat witness

- Owner [issue #818](https://github.com/dosibjrn/forever-sim/issues/818); current [PR #831](https://github.com/dosibjrn/forever-sim/pull/831), head `f3f9187` rebased onto current main. Canonical high-water is **PARTIAL 85/224** from merged #825; latest no-record experiment on `740ceb2` remained **85/224**, with no new Spell Power witness.
- Exact-head maintenance [#41788709671](https://github.com/dosibjrn/forever-sim/actions/runs/41788709671) is **FAIL**: `test_paid_winner_fallback_runs_when_source_baseline_fails` still expects an extra source-policy stat probe despite the two-evaluation cap. Fix the test expectation/actual call sequence **without increasing the paid budget**, then rerun focused and exact-head maintenance. Generic CI was still in progress at the last inspection.
- No merge or official M1 recorder at unchanged 85/224. Next real gate advance requires source-authorized executable Spell Power sensitivity (or another genuinely improved applicable stat), no invented epsilon/weights. Maximum remaining from 85/224 to full PASS is approximately **+0.04659 percentage points**.

### 4. Backlog — Paladin L20 unrestricted P3 source-naked executable baseline

- [Issue #845](https://github.com/dosibjrn/forever-sim/issues/845) records the first reproducible defect. Both official light runs [#41787910137](https://github.com/dosibjrn/forever-sim/actions/runs/41787910137) and duplicate [#41787945906](https://github.com/dosibjrn/forever-sim/actions/runs/41787945906) returned **BLOCKED_NO_NAKED_SUCCESS**, `real_source_search_evaluated=0`. Workflow SUCCESS was **not** gate PASS; ledger unchanged.
- Investigate actual naked-policy execution/refusal before attributing failure to the proxy actor; repair the first proven source/native invocation deficiency without inventing Warcraft mechanics. Work1 takes this after #817 or a later evidence-based reprioritization. **No unchanged recorder rerun.**

## Completed / no unchanged redispatch

- **Druid L60 Balance P7.4** current-code PASS on both post-#840 heavy runs [#41786536534](https://github.com/dosibjrn/forever-sim/actions/runs/41786536534) and [#41786566461](https://github.com/dosibjrn/forever-sim/actions/runs/41786566461); canonical receipt preserved. No new P7.4 run.
- Hunter L20 P3: `BLOCKED_NO_NAKED_SUCCESS`, zero paid source evaluations; no unchanged retry.
- Mage L20 P3: preserve 88/224 high-water; no unchanged retry.
- Mage L30 P3: preserve 85/224 high-water until a changed real producer exceeds it.
- P1/P2 retired; no GameIR rebuild, MythicSim self-validation or invented P3 weights. Only Merge dispatches official M1 runs and writes the canonical ledger.
