# WORK PRIORITY — live M1 queue

Refreshed against main `ffb67718bb2af6d1232a0878439f115d18058f3b`. Canonical ledger blob: `311bfb194ebd720d1105561d6e032a15359b3273`.

## Current M1 scoreboard

- **M1 measured: 2.1000%** (`measured_fraction=0.0210002413`).
- **27.972 / 1,332** measured gate-equivalents; **23 PASS / 17 PARTIAL** active-scope gate rows.
- **0 / 148** certified checkpoints. The measured float is diagnostic coverage, not certification. Only Merge writes `M1_PASSES.tsv`.

## Immediate dependency-ordered queue

### 1. Merge — Shaman L20 unrestricted P3 (single light measurement)

- **Gate:** `shaman:20:unrestricted:P3`; canonical ledger has **no row** (not yet measured, not PASS/FAIL).
- Existing `registry.py` Shaman source provider declares L10–L20 coverage; `wf_gate_p3_live.py` uses the real bounded **44-evaluation** paid scorer and selected native item-options client. This is a credible cheap first measurement, **not** a promise that source-naked policy or item context succeeds.
- **One dispatch request already exists** on [issue #131 comment](https://github.com/dosibjrn/forever-sim/issues/131#issuecomment-6624706584). Merge checks for ACK/active writer, then launches exactly one light production recorder on fresh main. Do not add another command. If BLOCKED, preserve the actual reason and do not repeat unchanged.
- Conditional maximum full-PASS gain: `1/1332` = **+0.07508 percentage points**. Any eligible PARTIAL earns only its actual measured fraction. No gain is credited before a trusted recorder.

### 2. Work1 — Priest L20 unrestricted P4/P5 native level-aware actor

- Existing owner [issue #817](https://github.com/dosibjrn/forever-sim/issues/817), updated to the exact native capability gap. **Unpark and execute this independently of Work2 #818.**
- PR #822 already merged the native ItemSparse options transport. The post-merge light recorder [#41779281303](https://github.com/dosibjrn/forever-sim/actions/runs/41779281303) invoked both gates but returned **BLOCKED**: `P4_P5_NATIVE_PAID_WHOLE_BUILD_EXECUTOR_NOT_CONNECTED`; it produced zero complete paid screens and zero source-action casts.
- Work1's exact selected fork audit ([evidence](https://github.com/dosibjrn/forever-sim/issues/817#issuecomment-6623513584)) shows the real missing capability: selected MythicSim `proto.Player` has no level field; native `new_character` unconditionally sets level 60; selected `go-tables.json` base stats are class/race max-level rows with no level dimension. A request-side `level:20` or CLI flag alone is not sufficient.
- **Next action:** implement a MythicSim-owned level-aware Player contract, requested-level actor preparation, and source-backed L20 base stats/conversions; connect the actor to the existing paid whole-build evaluator and real 2D/source-action screen. Rust tests first, then one exact-HEAD no-record Priest L20 P4/P5 producer showing actual actor level 20, COMPLETE paid screens and positive source-action casts. No level-60 proxy, guessed stats, Forever GameIR/SQLite fallback or new gate.
- If both gates eventually produce 2/6 comparable paid-screen behaviors, their conditional combined partial-inclusive M1 opportunity is **+0.05005 pp**. Not earned. Merge dispatches only after real eligible coverage is demonstrated; full PASS still requires the approved 30/300-second searches and 100-mob finalist.

### 3. Work2 — Mage L30 unrestricted P3 source-witness repair

- Owner [issue #818](https://github.com/dosibjrn/forever-sim/issues/818); current [PR #831](https://github.com/dosibjrn/forever-sim/pull/831), head `f3f9187e1c9688993406ef8c5ec5ef99213fab77`, based on main `384e584`.
- Canonical high-water remains **PARTIAL 85/224** from merged #825. The positive +50 Intellect witness is preserved; no new Spell Power witness or M1 increment is demonstrated. The PR's exact-head selected-Rust and generic source-paid jobs passed, but maintenance [#41788709671](https://github.com/dosibjrn/forever-sim/actions/runs/41788709671) **failed one test** (391 passed, 1 failed).
- Exact failure: `test_paid_winner_fallback_runs_when_source_baseline_fails` expects three calls. Actual bounded production sequence is two evaluations: (1) source-policy baseline with the observed `mage:fireball` opening, which fails; (2) exact paid-search-winner perturbation using that same opening. The source-policy perturbation must not run without a valid source-policy baseline. Correct the fixture to assert this two-call sequence; **do not increase the 44-evaluation cap or invent a baseline**.
- After the fixture correction, rerun exact-head maintenance and one no-record Mage L30 P3 producer. Compare against 85/224; no merge or official M1 dispatch at an unchanged result. Next genuine gate advance requires a source-authorized executable positive stat witness. No synthetic weights or GameIR workaround.

### 4. Backlog — Paladin L20 unrestricted P3 source-naked executable baseline

- [Issue #845](https://github.com/dosibjrn/forever-sim/issues/845) records the first reproducible defect. Both light recorders [#41787910137](https://github.com/dosibjrn/forever-sim/actions/runs/41787910137) and duplicate [#41787945906](https://github.com/dosibjrn/forever-sim/actions/runs/41787945906) returned **BLOCKED_NO_NAKED_SUCCESS**, `real_source_search_evaluated=0`. Workflow SUCCESS was not gate PASS; ledger unchanged.
- Work1 takes this after #817, unless later measured evidence reprioritizes. Inspect actual source-naked attempted/blocked reasons and repair only the first proven production deficiency. Do not attribute the failure to a proxy annotation without evidence, invent source mechanics/base stats/weights, or rerun unchanged.

## Completed / no unchanged redispatch

- **Druid L60 Balance P7.4** current-code PASS on both post-#840 heavy runs [#41786536534](https://github.com/dosibjrn/forever-sim/actions/runs/41786536534) and [#41786566461](https://github.com/dosibjrn/forever-sim/actions/runs/41786566461); the canonical receipt remains the single accepted row. No further P7.4 run.
- Hunter L20 P3: `BLOCKED_NO_NAKED_SUCCESS`, zero paid source evaluations; no unchanged retry.
- Mage L20 P3: preserve the 88/224 high-water; no unchanged retry.
- Mage L30 P3: preserve the 85/224 high-water until a changed real producer exceeds it.

## Operating constraints

- Merge alone dispatches official M1 recorders and writes `M1_PASSES.tsv`; Prio maintains this queue and submits requests on existing owner issues.
- No M1 recorder was active at this refresh. Never launch a second M1 writer or duplicate a request already ACKed/launched.
- Prioritize real active P3–P7.5 production progress. No P1/P2 work, retired GameIR search runners, HPS/TPS witness work, MythicSim self-validation, invented positive weights or fabricated M1 rows.
