# FOREVER SIM — active M1 work queue

**Policy:** maximize genuine partial-inclusive M1 measured-float per total implementation, verification and compute time. Active gates: P3–P6 and P7.1–P7.5 (1,332 checkpoint-gate pairs). **Only Merge** dispatches the trusted recorder and writes `docs/planning/M1_PASSES.tsv`. MythicSim Rust owns Warcraft facts and legal optimization choices; Forever owns scenarios, search and scoring. No P1/P2, GameIR rebuild, duplicate legality, fabricated weights, MythicSim mechanics audit or unchanged heavy rerun.

**Last published M1 baseline:** trusted [one-shot Actions #41775113953](https://github.com/dosibjrn/forever-sim/actions/runs/41775113953), ledger commit [`4f504678`](https://github.com/dosibjrn/forever-sim/commit/4f504678f28eec3107ddbae35bf1615e59fc835e). **M1 measured: 2.08459033% (float=0.0208459033)** = 27.767/1,332 measured equivalents; **22/1,332** accepted PASS gates; **0/148** certified checkpoints. This is the last published baseline, not the result of the post-fix P7.4 recorder currently running below.

## Current in-flight Merge action

- **Druid L60 Balance P7.4:** [PR #819](https://github.com/dosibjrn/forever-sim/pull/819) is merged at `0c0a094d9669a85c88f7be0158b048ee67229cc9`. The single post-fix frozen 1,000-fight recorder [#41778065670](https://github.com/dosibjrn/forever-sim/actions/runs/41778065670) is **in progress**. Let it finish; do not repeat the 300-second search or start a concurrent ledger writer. No new P7.4 PASS is claimed yet.

## Next queue

### #1 — Merge: one-shot Hunter L20 unrestricted P3 measurement — [#827](https://github.com/dosibjrn/forever-sim/issues/827)

- **Baseline:** no `hunter:20:unrestricted:P3` row in the current M1 ledger and no existing task for this exact measurement.
- **Why this is the best next measurement:** Hunter's production profile is verified through L20, the existing gear bridge has a Hunter role and canonical per-level items, and P3 is the approved fast gear-scoring smoke (bounded source search, up to 44 evaluations), not a 30/300-second or 100-mob run.
- **Action:** after #41778065670 is terminal, run the existing production gate once on fresh `main` through the trusted Merge recorder: `python tools/wf_gate.py --class hunter --level 20 --spec unrestricted --gate P3`. Do not add code or change the predicate.
- **Conditional upside, not earned:** one genuine PASS adds `1/1332` = **+0.07508 percentage points**. If the actual run fails, only the recorder's eligible measured PARTIAL may count; report exact result and do not retry unchanged code.

### #2 — Work1: Priest L20 unrestricted P4/P5 native paid-search repair — [#817](https://github.com/dosibjrn/forever-sim/issues/817)

- **Baseline:** trusted [#41775113953](https://github.com/dosibjrn/forever-sim/actions/runs/41775113953) returned BLOCKED for both gates with `SOURCE_COLD_SEARCH_IR_OR_GEAR_ROLE_UNAVAILABLE`; neither has an M1 row.
- **Latest slice:** [PR #822](https://github.com/dosibjrn/forever-sim/pull/822) queries the selected Rust `item-options` source on the Priest path and passed [310/310 focused regressions #41777980141](https://github.com/dosibjrn/forever-sim/actions/runs/41777980141). It is still open and is **not** a paid whole-build/2D execution: no complete paid screens or source-action casts, so no M1 credit.
- **Next action:** continue #817 by constructing/preparing a real native Priest L20 candidate and connecting it to the existing paid whole-build/world screen; run one bounded no-record producer. Only hand off to Merge after actual COMPLETE paid screens and source-action casts. Do not invent a Python Priest role, SQLite fallback or new GameIR adapter.
- **Conditional upside, not earned:** if both gates genuinely reach 2/6, about **+0.05005 percentage points** combined. Do not launch 30/300-second or 100-mob acceptance just to collect partial credit.

### #3 — Work2: Mage L30 unrestricted P3 paid stat-witness repair — [#818](https://github.com/dosibjrn/forever-sim/issues/818)

- **Baseline:** official [#41775113953](https://github.com/dosibjrn/forever-sim/actions/runs/41775113953) recorded FAIL / PARTIAL **44/224**.
- **First reproduced defect:** the paid source-policy witness returns `NO_POSITIVE_SOURCE_POLICY_WITNESS` for Agility, AP, Intellect and MP5. Its baseline evaluation fails for both an empty prefix and the reported `fire_blast:8412` ×2 prefix. This isolates the next action to making a real executable baseline available for before/after stat perturbation—not a broad native-axis audit.
- **Current Work2 branch:** `ccb5a8a6d11054caf9990fedfb5a7bc70c54c9fa`; generic source-paid, maintenance and selected-Rust checks [#41778805128](https://github.com/dosibjrn/forever-sim/actions/runs/41778805128), [#41778805206](https://github.com/dosibjrn/forever-sim/actions/runs/41778805206) and [#41778805293](https://github.com/dosibjrn/forever-sim/actions/runs/41778805293) were in progress at last inspection.
- **Action:** finish the focused baseline-evaluation repair and run one exact-HEAD no-record P3 producer against 44/224. Merge records only a genuine comparable improvement or PASS. No fabricated weight/epsilon, Python legality table or SQLite fallback. Keep unrelated Work2 draft [PR #537](https://github.com/dosibjrn/forever-sim/pull/537) DRAFT/HOLD.

**Completed / do not redispatch:** Merge's [#813](https://github.com/dosibjrn/forever-sim/issues/813) is closed; Mage L20 P4/P5 each have genuine PARTIAL 4/6. Work1's [#807](https://github.com/dosibjrn/forever-sim/issues/807) and [#812](https://github.com/dosibjrn/forever-sim/pull/812) native activation are complete. Preserve existing accepted receipts; only materially affected gates are revalidated.