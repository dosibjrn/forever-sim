# Balance Druid L60 — WF669 P7.4 review and WF670 fixes

## Historical WF669 provenance

- [Run 40972109624](https://github.com/dosibjrn/mage-level-sim/actions/runs/40972109624), artifact `wf669-p74-native-evidence` (artifact #12940323970, SHA256 `884f62dc1ebbac267974ee2dcd2f309c5547a83cc3957e7c0d3e8ca18843af55`).
- Machine-readable summary: [wf669_original_report.json](wf669_original_report.json). Pinned Rust source commit `666fe17a42682068a3c8497d88d5fa3732cbdfb9`.
- 6,704 paid successful screens + 783 failed screens = 7,487 recorded screen attempts. Of 783 failures **all 783 contain an empty `error` field** in the original artifact. Consequently their actual stderr/refusal categories **cannot** be reconstructed from preserved evidence. Assigning specific causes would fabricate evidence. The raw historical `failures.json`, `paid_candidates.json`, `reranked.json`, `frozen_winner_request.json` remain in the linked artifact, not all duplicated in Git.
- Old winner: 797.362348 DPS / 4,000 stochastic iterations, against 728.193613 external reference (99% floor 720.911676). This is **not a certified legal item set and not a PROCESS P7.4 PASS**, merely the reported old native diagnostic.

## WF670 technical changes

- Intersect source SQLite item candidates with **the exact Rust engine source** `data/items.jsonl` and `data/enchants.jsonl` from pinned commit, instead of assuming item IDs are interchangeable. Fail closed for missing IDs, missing scaling, mismatched name/type, known class/armor restrictions, level, slot and known enchant restrictions.
- Detect duplicate equipped item IDs (including two rings/trinkets) and Rust unique limit categories, preserve all non-ID equipment fields, freeze talents/APL/encounter and every non-equipment request dimension.
- Record illegal combinations separately from genuine native failures, including phase, affected IDs, category, return code and **stdout and stderr**; missing/unsupported items are never scored as legal candidates.
- Independent original winner audit: `p74_audit_wf669.py` inspects **all 16 historic winning IDs** against the source SQLite + pinned Rust engine. The new PR workflow saves `wf669_original_winner_audit.json` even if the old winner is rejected; it does not promote it to PASS.
- PR-triggered contracts and real native run. `actions/checkout(lfs:true)` plus SQLite magic check prevents silent LFS pointer ingestion. Rust executable is reused via WF652 artifact and SHA256SUMS checked; engine and source dataset SHA256 are saved with new diagnostic evidence.
- Strict 300-second wall-clock including setup, search, rerank and holdout (timeouts stop the run, never silently extend the budget).

## Limits / acceptance

New evidence is published as GitHub Actions artifact `wf670-p74-legality-and-native-evidence`, with `paid_candidates.json`, `failures.json`, `rejected_combinations.json`, `reranked.json`, `frozen_winner_request.json`, `winner_identity_audit.json`, `report.json`, SHA provenance and historical audit.

Source and Rust item identity can be cross-checked, but **full phase/faction/profession restrictions not present in either input DB, arbitrary item-effect semantics, and a live gsim-2D↔Rust causal trace are NOT certified**. Do not treat an above-floor native holdout as a full P7.4 technical gate PASS. P7.5 is a separate workstream.
