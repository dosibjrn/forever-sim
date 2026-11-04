# FOREVER SIM — active M1 work queue

**Policy:** maximize genuinely incremental partial-inclusive M1 measured-float per total implementation, validation and compute time; keep certified PASSes and the 148-checkpoint objective distinct. Active gates: P3–P6 and P7.1–P7.5 (1,332 pairs). **Only Merge** dispatches the trusted recorder and writes docs/planning/M1_PASSES.tsv. P1/P2 are retired; no new GameIR/Python Warcraft-legality work.

## Verified scoreboard

Snapshot read from main at c9fc60fa7bfc:
- Canonical ledger arithmetic: **1.92437683%** (float=0.0192437683), **22/1,332 PASS**, **0/148 certified**.
- The arithmetic includes Mage L30 unrestricted P3 **PARTIAL 46/160** from [Actions #41764632715](https://github.com/dosibjrn/forever-sim/actions/runs/41764632715), published in [commit #847e6b0](https://github.com/dosibjrn/forever-sim/commit/847e6b00384fbbf4c1ef2bb24eb674aedf4cd069). That run used the legacy SQLite item-legality fallback, contrary to owner decision [#359](https://github.com/dosibjrn/forever-sim/issues/359); it is a recorded diagnostic row, **not native ItemSparse evidence**. Excluding it, the source-authority-compliant baseline is **1.90279275%**. Merge must resolve the row's provenance in #790; only Merge may edit the ledger/history.
- Latest accepted gate remains Druid L60 unrestricted P6: [Actions #41762368553](https://github.com/dosibjrn/forever-sim/actions/runs/41762368553), terminal production PASS, two complete 100-mob replays, T30=14.3915047718 s/mob, T300=15.7885622706 s/mob, ratio 0.911514584.
- Mage L30 P4 probe [#41765124674](https://github.com/dosibjrn/forever-sim/actions/runs/41765124674) failed with LIVE_GATE_EXECUTION_FAILED:IndexError:list index out of range before a complete paid screen/action count; no P4 row or credit. Issue #788 is closed as a completed measurement, not a PASS.
- No active M1 recorder run was observed at this snapshot (0 in progress). Merge rechecks live Actions and the ledger immediately before every dispatch.

## #1 — Work2: native P3 integration — [#754](https://github.com/dosibjrn/forever-sim/issues/754), [Forever PR #781](https://github.com/dosibjrn/forever-sim/pull/781)

- Combined MythicSim fork PR #7 is merged. Exact combined fork pin **5f116607b955a87c124b67a3ba4750ba0c508e42** contains both native ItemSparse/item-options and the P7.4 world-ACK repair. Current fork main is 23641daaba3c.
- Forever PR #781 is open, non-draft, current HEAD **473d374681c4052695ddb5f90f298c98499a52ca**, base **055b1665c5d93ffb150aa399b209eb3f7dc0dd34**, mergeable_state=unstable. Its gitlink points to the combined 5f1166 pin. Its P3-only recorder path now computes p3_native_needed, hydrates/verifies/builds the exact submodule, sets FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN, and fails closed if the binary is absent. The P3 activation gap is resolved in this PR.
- Exact combined-pin selected-engine/no-record provider run [#41767415596](https://github.com/dosibjrn/forever-sim/actions/runs/41767415596) SUCCESS. It executed the real native item-options CLI:
  - Priest L20: 1,314 known items, 2,267 unknown-level exclusions, 44/220 assertions, partial_level_unknown.
  - Mage L20: 1,306 known items, 2,239 unknown-level exclusions, 88/224 assertions, partial_level_unknown.
  Both are provider FAIL/PARTIAL results, not P3 PASSes and not official M1 records. Mage L30 still needs its own no-record check on the combined pin.
- Exact-head checks for PR #781: selected-engine/P3 provider #41767415596 PASS; maintenance #41767415658 PASS; generic source-paid #41767415586 PASS; Work2 28-profile stage-5 sweep #41767415593 was in progress at last check; Work1 stage-5 replay #41767415588 and bootstrap #41767415589 failed; aggregate native session/ACK #41767415656 failed outside the successful P3 provider path. Classify each red job by its exact failing step; do not convert unrelated diagnostics into a P3 verdict.
- The PR currently changes 12 paths: .github/workflows/m1-on-demand-record.yml, .github/workflows/maintenance-evidence-tests.yml, .github/workflows/rust-submodule-verify.yml, integrations/mythicsim-rust/engine, integrations/mythicsim-rust/port_native_typed_rng.py, integrations/mythicsim-rust/tests/test_port_native_typed_rng.py, src/game/checkpoint_p3_smoke.py, src/game/native_p3_item_options.py, tests/gates/test_wf_gate_class_cli.py, tests/test_native_p3_item_options.py, tools/wf_gate.py, tools/wf_gate_p3_live.py. It excludes Merge-owned M1 ledger/history and Prio-owned WORK_PRIORITY. It is behind current main (base 055b1665c5d93ffb150aa399b209eb3f7dc0dd34); rebase/update to current main, rerun exact-head checks, then Merge reviews. Do not claim all CI green while mergeable_state is unstable.

## #2 — Merge: one non-heavy native P3 measurement batch — [#790](https://github.com/dosibjrn/forever-sim/issues/790)

- Targets: priest:20:unrestricted:P3 and mage:20:unrestricted:P3. Add mage:30:unrestricted:P3 to the same batch only after a no-record provider check on the combined 5f1166 pin and explicit Merge resolution of the old SQLite-derived 46/160 row. Do not create a separate Mage L30 dispatch.
- Previous official baseline [#41747651321](https://github.com/dosibjrn/forever-sim/actions/runs/41747651321): Priest L20 failed before item assertions with P3_NO_LEGAL_ITEMS_IN_CURRENT_DB; Mage L20 PARTIAL 57/155.
- Combined-pin no-record provider evidence #41767415596 gives Priest 44/220 and Mage 88/224. If confirmed by the trusted recorder, the expected eligible incremental partial credit over the current source-valid baseline is about **+0.01690 pp**; this is not earned credit. The full PASS ceilings remain Priest +0.07508 pp and Mage L20 +0.04747 pp.
- Do not dispatch until PR #781 is merged to current main and exact combined-pin provider checks are green. Then Merge re-reads main, ledger and live Actions and dispatches one non-heavy batch:
  /m1-run priest:20:unrestricted:P3 mage:20:unrestricted:P3 mage:30:unrestricted:P3
  Omit Mage L30 if its no-record provider check has not succeeded. Only Merge records the producer result.

## #3 — Work2: repair the P4/P5 partial-search crash — [#797](https://github.com/dosibjrn/forever-sim/issues/797)

- The single non-heavy Mage L30 P4 probe #41765124674 crashed before producing a partial. The likely path is an empty executable full-point talent frontier: rankless indexed placeholders have max_rank=0; bounded_full_point_talent_frontier can return no allocations; _source_talent_policy_variants then returns an empty policies_by_talent; search_bounded_joint_frontier indexes policies_by_talent[0] unconditionally at line 2963. The workflow swallowed the traceback, so #797 requires a focused Mage L30 regression to confirm before patching.
- Required fix: only the 6-second search_only P4/P5 partial path may use an explicit non-certifying unallocated-talent baseline if the canonical validator accepts it; label it UNALLOCATED_BASELINE_ONLY, award no talent-unlock credit, and count only actual source actions cast in completed paid screens. If invalid, return a structured BLOCKED result instead of IndexError. Full 30s/300s acceptance stays strict and cannot use the baseline. Add tests for both paths.
- Work2 owns this independent source-search repair; do not fold it into the P3 PR unless necessary. After merge, Merge rechecks main/ledger/Actions and runs one non-heavy Mage L30 P4 probe. No heavy/full P4 retry.

## #4 — Work1: Druid L60 Balance P7.4 native-world ACK/flush repair — [#131](https://github.com/dosibjrn/forever-sim/issues/131), [Forever PR #793](https://github.com/dosibjrn/forever-sim/pull/793)

- The P7.4 repair is included in combined fork pin 5f1166. Forever PR #793 is open, non-draft, current HEAD **1a53885214e33a5e783b28ffc54ce891c5a1d489**, base **c9fc60fa7bfc23836d4ff8deffc1f0570719d591**, and also points to 5f1166. It must rebase to current main and rerun exact-head selected-submodule/native session-world-ACK checks before merge. No P7.4 holdout is authorized by this queue update.
- Canonical P7.4 remains PARTIAL 704.6605/720.9117, about +0.00169 pp remaining. Previous unchanged heavy runs #41761122638 and #41761177857 failed with RUST_WORLD_UNFLUSHED_EVENTS; do not repeat unchanged.
- After PR #793 is merged and exact combined-pin checks pass, Merge alone dispatches one frozen 1,000-fight P7.4 holdout and owns any M1 recording.

## Selection comparison and operating rules

- P3 native provider results offer about +0.01690 pp of likely eligible measured-float improvement if the official recorder confirms them; this is the highest current measured opportunity.
- P4/P5 crash repair is an independent low-cost path to a new measured partial; no credit until the production recorder reports it.
- P7.4 has only about +0.00169 pp headroom and needs the expensive frozen holdout; keep Work1's repair moving in parallel.
- Druid L30/L40 unrestricted P6 already have PARTIAL 200/200 and are saturated; unchanged reruns add no partial-inclusive float.
- No HPS/TPS work, no P1/P2 reactivation, no Rust-validation side quest, no duplicate P6/P7.4 dispatch, and no manual M1 ledger edits.
