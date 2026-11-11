# WORK PRIORITY — live executable assignments

**Owner P0, 2026-11-11 — M0.5 sampled native optimization is DONE; M0.6 is the next product milestone.** Do not run strides 20/10/5/1 again, reopen an accepted M1 PASS, invent Warcraft mechanics, or mislabel sampled scores as continuous leveling. Reuse the original paid receipts.

## Top P0 — integrate and publish the sampled native build guide

**Work2 / Merge — existing [M0.6 PR #1429](https://github.com/dosibjrn/forever-sim/pull/1429), current exact HEAD `73503f812d14e10be553bc63adab4feb46699624`.** The PR is open, non-draft and mergeable against latest inspected main `2c2fb5a072699c0a91d604276fbaee0602629108`. Its production `native-guide` consumes the **original, completed** stride-1 JSON offline, without starting Rust or repeating paid native samples. It renders per-level talent ranks and rank deltas, native gear IDs, pet/APL, paid time and terminal recovery, source request SHA and competing sampled totals, explicitly refusing to claim XP/travel/training/continuous gameplay.

- **Exact-HEAD changed-code verification:** [Actions #42987924688](https://github.com/dosibjrn/forever-sim/actions/runs/42987924688), `native-paid-route` **SUCCESS, 290 focused tests passed**; expensive native jobs skipped. M1 affected gates: none.
- **Next executable:** Merge review/integrate #1429 with the existing measured receipt and exact-head focused tests; Work2 produce/publish the authentic Markdown guide from unpacked `m05-l20-l60-stride1.json` via `python -m src.v2.runner native-guide --in m05-l20-l60-stride1.json --out GUIDE.md`. Keep source data and displayed scope unchanged. The guide is a product improvement, **not M0.6 continuous-route completion**.
- **Preserved native source:** [stride-1 Actions #42985475032](https://github.com/dosibjrn/forever-sim/actions/runs/42985475032), [original artifact #13839219023](https://github.com/dosibjrn/forever-sim/actions/runs/42985475032/artifacts/13839219023), producer `9315b3d`, pinned Rust `dd53c747`. **Actual `sparse-optimizer-real` job SUCCESS**: 41/41 sampled L20–60 levels, two hostile world mobs per level, balanced one iteration, measured full terminal HP and mana recovery, 270 native candidate attempts / 234 qualified / 36 explicit refusals / 20 source-matched paid-cache hits, three compatible paths tied at **3515.550 s**. Merge inspected **41/41 original winner native receipts, SHA256, two lethal 2D ACKs and both resources full** [issue #1421](https://github.com/dosibjrn/forever-sim/issues/1421). Overall workflow is red **only** because an older separate test job failed; corrected focused tests subsequently passed. No native rerun warranted.

## Next P0 — implement genuine M0.6 continuous advancement, not a denser sample

**Work2 — existing [generic route issue #1104](https://github.com/dosibjrn/forever-sim/issues/1104).** After publishing the guide, extend the **same native-backed range coordinator** by one smallest genuine retained-actor level-to-level world segment, starting at an observed L20 sample and attempting L20→21. Keep the previous actor, real gsim world/ACK decisions, native-paid HP/mana/time, and distinguish actual XP/travel/training/level advancement from unsupported or unmeasured operations. Do not stitch independent per-level prepared actors into a claimed continuous route; do not use fixed travel, level-up or restoration estimates; do not require a full 10–60 replay for the first reviewable slice. Preserve existing compatible receipts as baselines and compare only genuinely paid compatible alternatives. Ship a focused changed-behavior regression and one bounded real native proof when ready. If a required source API is missing, show the **exact native refusal/call site** and continue independently with supported retained-state behavior.

**Work1 — existing [native source issue #1052](https://github.com/dosibjrn/forever-sim/issues/1052).** Inspect selected pinned Rust persistent options/prepare/evaluate/world/ACK interface and the first real M0.6 level-advancement attempt. Implement the **smallest reusable missing native state/XP/travel/training interface only when demonstrated absent**; Rust owns all Warcraft rules, Forever does not reproduce them. Preserve the already working all-level L20–60 actor support and source-native full recovery; do not redo broad engine checks or requalify M0.5.

**Merge — immediate integration** of already-green #1429, then only focused verification of the next actual changed native boundary. The independent [#1427](https://github.com/dosibjrn/forever-sim/pull/1427) and [#1428](https://github.com/dosibjrn/forever-sim/pull/1428) cache fixes are **already merged** as `104f943a` and `2c2fb5a`; do not review/dispatch them again. The official M1 ledger is untouched and only Merge can record new genuine M1 gate PASSes.

**Clean — independent real-waste removal.** Only act on newly reproduced Forever-side refusal, needless incompatible receipt invalidation, duplicated engine source semantics or work that could cause M0.6 to pay identical existing worlds. No speculative audit, no unrelated source rewrite, no duplicate M0.5 test or code churn.

**Prio — live dispatch.** Keep attention on guide integration and the first **actually executed** retained-actor adjacent-level segment. New priority changes only after a measured source result, concrete missing interface, or shipped capability; no hourly queue-recap commits.

## Completed source-native milestone baseline (do not rerun)

- **M0.3:** direct persistent Rust API merged via [fork #50](https://github.com/dosibjrn/mythicsim-forever-engine/pull/50); native recovery [fork #49](https://github.com/dosibjrn/mythicsim-forever-engine/pull/49) also merged. Rust `dd53c747` is the engine pin for measured M0.4/M0.5 output.
- **M0.4 stride 20:** [#1418](https://github.com/dosibjrn/forever-sim/pull/1418), [real run #42980239306](https://github.com/dosibjrn/forever-sim/actions/runs/42980239306), 3/3 samples, three ranked compatible paths, best 267.83 s, paid dual-resource recovery.
- **M0.5 stride 10:** [#1422](https://github.com/dosibjrn/forever-sim/pull/1422), [native-paid run #42981742152](https://github.com/dosibjrn/forever-sim/actions/runs/42981742152), 5/5 samples, three paths, best 410.73 s.
- **M0.5 stride 5:** merged [#1425](https://github.com/dosibjrn/forever-sim/pull/1425), [native-paid run #42984895024](https://github.com/dosibjrn/forever-sim/actions/runs/42984895024), 9/9 samples, three paths, best 753.33 s.
- **M0.5 stride 1:** native-paid job [#42985475032](https://github.com/dosibjrn/forever-sim/actions/runs/42985475032) success as detailed above. **This is not 41 levels of continuous XP gameplay, not a single end-to-end 10–60 journey and not an M1 certificate.**

## Clean escalations for Prio

<!-- Only new source-linked actionable findings; Prio disposes them in this live queue. No escalation pending. -->
