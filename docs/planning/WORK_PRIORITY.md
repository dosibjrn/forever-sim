# FOREVER SIM — active work priority

**Purpose:** shortest path to 148/148 genuinely certified checkpoints. **Priority #1 is to eliminate the duplicated Python GameIR/game-legality stack** via the selected MythicSim Rust interface. The owner decisions [#357](https://github.com/dosibjrn/forever-sim/issues/357) and [#359](https://github.com/dosibjrn/forever-sim/issues/359) override superseded implementation recipes in older issues.

This is a current execution queue, not a changelog or second gate/evidence system. History stays in Git; formal acceptance stays in [PROCESS](../../PROCESS.md), [gate contracts](../gates/README.md) and the Merge-owned [M1_PASSES.tsv](M1_PASSES.tsv). Agent responsibilities: [AUTONOMOUS_AGENTS](AUTONOMOUS_AGENTS.md); ideal end state: [REPOSITORY_STRUCTURE](../REPOSITORY_STRUCTURE.md).

## Active queue — execute in this order

### #1 P0 — remove GameIR and duplicate game rules (#357 / #359 / #333 / #332)

#### #1a — FIRST EXECUTABLE TASK: remove ALL redundant Forever spell/acquisition/source proof blockers

**Owner decision 2026-11-03, P0 / #1 ahead of cosmetic cleanup and new audits.** [Merged PR #635](https://github.com/dosibjrn/forever-sim/pull/635) removed the live P1 trainer/learned-spell proof. **Continue the same deletion across every remaining caller, class, level, spec, P1–P7.5 gate, search and route path.** This is **not** a task to collect new evidence, validate MythicSim's Warcraft rules, or prove trainer/quest/learned-rank acquisition inside Forever. MythicSim Rust is the sole authority for spell/rank availability, talent/gear/enchant/APL/game legality, and actual effects. Forever passes candidates to native, consumes VALID/INVALID/UNSUPPORTED/error, checks real behavior/optimizer reachability and records existing gates.

**Concrete remaining migration/deletion queue (reinspect actual latest-main call graph on each cycle):**

1. **P1/P2 acceptance and source-admission readers:** eliminate independent `_acquisition` / `_status`, spellbook/source-index evidence and client-side eligibility vetoes in `src/game/data/forever/source_checkpoint_p1_acceptance.py` and the other `source_checkpoint_*` admission paths. Replace *live* callers with native prepare/execute responses first; do not merely make a Python proof check always return LEGAL. The old standalone P1 proof in `tools/wf_gate_p1_live.py` was removed by #635; finish the still-live counterparts.
2. **Route/world acquisition proof:** retire `src/game/level_legality.py::validate_level_state(require_world_acquisition)` and `src/game/data/forever/source_acquisition.py::audit_learned_action_legality` as independent spell-learned acceptance vetoes; migrate their real callers in `src/v2/source_budgeted_level_route.py`, `src/game/data/forever/source_world_acquisition.py` and associated route tools/tests. **Do not remove real route, spatial/2D causality, persistent resource, chainpull, native event or 100-target behavior** required by existing gates. Move needed execution behind the selected MythicSim interface.
3. **Source-proof databases, utilities and fixtures:** inventory all live consumers of `src/game/data/forever/source_checkpoint_acquisition.py`, `source_acquisition_events.py`, `source_acquisition.py`, `tools/ingest_source_acquisition_evidence_sqlite.py`, `tools/ingest_source_acquisition_entities_sqlite.py`, `tools/wf332_druid20_acquisition_evidence.py` and historical proof-only tests. Remove redundant proof creation, ledger assertions, diagnostic blockers, imports and fixtures **after** their production callers no longer need them. #635 already deleted the standalone nine-class acquisition audit CLI and its tests; do not reintroduce it.
4. **All other gate and optimizer blockers:** search for `SOURCE_ACTION_LEGALITY_UNRESOLVED`, `INDEX_LEVEL_HINT_IS_NOT_ACQUISITION`, `SOURCE_SPELLBOOK_*`, `BLOCKED_*ACQUISITION*` and analogous independent source/semantic/legality "proof missing" failures in P1–P7.5, candidate filtering and CI. Delete the *redundant proof requirement*, not actual engine refusal, behavior assertions, search budgets or acceptance predicates. Do not add another proof-only test or substitute a Python validity oracle.

**Execution contract:** Prio tracks the first genuinely live instance and assigns/implements it; Work1/Work2 migrate independent consumers to exact-SHA MythicSim; Clean deletes now-unused rules/data/receipts/tests and moves immediately to the next real dependency. Every implementing cycle must push a meaningful tested source deletion or native-caller migration (PR/commit), not only a report. Preserve existing accepted M1/PASS records; a removed blocker is **not** itself a new PASS. Finish only when **no production gate/search/route requires Forever-generated spell acquisition or equivalent source-legality proof**, and remove its dead evidence plumbing.




**End state:** zero live GameIR consumers, Python Warcraft-rule/legality tables or duplicate combat/world execution. **MythicSim Rust exclusively owns** ability/rank acquisition, talent/gear/enchant/APL game legality, spell/combat effects, and required world mechanics. **Forever owns** scenarios, optimizer candidate search/scoring, native request/response plumbing, engine provenance and existing P1–P7.5 gate bookkeeping. Do not build another Python rules adapter, shadow GameIR or source-backed legality subsystem.

**Work1 (#1 implementation owner):** hand off the existing bounded [#624](https://github.com/dosibjrn/forever-sim/pull/624) P7 PR to Merge without discarding it; then prioritize the **first real gate-critical GameIR/runtime caller** and replace its game-fact/legality/execution path through selected MythicSim Rust. Use [#357](https://github.com/dosibjrn/forever-sim/issues/357) and [#359](https://github.com/dosibjrn/forever-sim/issues/359) for ownership; coordinate P1/P2 caller scope with Prio [#332](https://github.com/dosibjrn/forever-sim/issues/332). Before deleting old Python code, run focused tests of the **Forever caller**: native request forwarding, preservation/classification of returned `VALID` / `INVALID` / `UNSUPPORTED` / errors, and the existing applicable end-to-end production behavior. **Do not verify Rust's talent caps, source tables or game-law decisions in separate tests.** A native refusal is authoritative, not automatically an engine defect or a reason for a Python fallback; only a demonstrated missing *required interface/capability* is an implementation blocker.

**Clean (#1 deletion owner):** stop cosmetic, empty-file and facade-only cleanup while a meaningful GameIR caller migration is available. Maintain a concrete live caller → native replacement → focused verification → deletion inventory under existing [#333](https://github.com/dosibjrn/forever-sim/issues/333)/[#357](https://github.com/dosibjrn/forever-sim/issues/357); remove replaced GameIR modules, source/legality tables, imports, shims and tests incrementally after callers run successfully on selected Rust. Do not remove live functionality speculatively or edit another agent's active branch.

**Prio (#1 unblock owner):** identify a **demonstrably absent required native API/capability** preventing a high-impact caller migration, not a perceived problem in MythicSim's rules. Only for that missing capability implement/assign a scoped Rust-fork PR (not a Forever Python workaround). Treat native game-legality decisions as authoritative; do not audit or revalidate their correctness or mistake a refusal for a defect. The migration is complete only when no duplicated live GameIR or source-legality execution remains.

**Every Work1/Work2/Clean cycle must land a real pushed implementation increment** (commit/PR with focused validation); CI-only, status-only or PR-comment-only reports do not satisfy the cycle. If one migration is blocked, switch to a different executable independent slice; never fabricate a meaningless diff. See the agent delivery contract.

**Fork-to-production path:** normal branch → source/test PR → merge in [owned MythicSim fork](https://github.com/dosibjrn/mythicsim-forever-engine) → tested exact-SHA gitlink PR in Forever → native caller migration/deletion PR. No floating engine refs and no changes to historical PASS ledger. The privileged [rust-upstream-fork.yml](../../.github/workflows/rust-upstream-fork.yml) bootstrap is a separate, owner-guarded operation; it is **not required** for normal fork PR creation or merge. See [RUST_UPSTREAM_FORK](../RUST_UPSTREAM_FORK.md).

### #2 P0 — Work2 #15: joint optimizer, using MythicSim-owned legality

Continue [#15](https://github.com/dosibjrn/forever-sim/issues/15) as the independent #2 lane, but treat its historical “full source-backed legality adapters” wording as superseded by #359. The optimizer proposes gear/talents/APL candidates; **MythicSim validates/prepares/simulates them** and returns concrete valid/invalid/unsupported outcomes. Treat native talent refusals as authoritative results. Investigate and request a Rust-fork change only if a **required API/capability is demonstrably missing**, not to revalidate Rust talent rules; remove Python-side duplicated constraints instead of implementing new validators. Keep the shared generic search kernel and small paid regressions. The 28-profile 5s matrix remains diagnostic and 0/28 is not a certified result. Do not repeat unchanged 30s/300s sweeps or holdouts.

[#19](https://github.com/dosibjrn/forever-sim/issues/19) and draft [#537](https://github.com/dosibjrn/forever-sim/pull/537) remain HOLD pending a published/pinned suitable Rust implementation, damaged-actor paid HP-recovery proof and genuine 100-target trace. Do not claim that the merged source port alone establishes this.

### #3 P0 — finish the first genuine native↔world P7 checkpoint

Work1 retains the existing [#7](https://github.com/dosibjrn/forever-sim/issues/7) and in-flight [#624](https://github.com/dosibjrn/forever-sim/pull/624) evidence/handoff; after the #1 native replacement unlocks it, continue actual Rust↔2D causality, 300s search and independently frozen 1,000-iteration stochastic final where approved. The selected typed Balanced RNG pin currently remains `deb366e986dbc156e2242ddac3ac8c4ac854c107`; no World/2D diagnostic alone is a P7 PASS. Do not rerun unchanged heavy holdout just to fill the ledger.

### Parallel roles

- **Prio:** [#131](https://github.com/dosibjrn/forever-sim/issues/131), [#11 P1](https://github.com/dosibjrn/forever-sim/issues/11), [#12 P2](https://github.com/dosibjrn/forever-sim/issues/12) via real native effect and legality; no second GameIR.
- **Merge:** integrate tested bounded PRs and alone launch official affected-gate runs/write eligible M1 evidence. A structural migration is mergeable before the whole checkpoint passes if supported behavior is preserved.
- **All agents:** read newest main and unresolved owned PR feedback first; preserve already accepted gate evidence. Prefer **reuse → native bridge → remove duplication** before unrelated optimization or diagnostic work.

## Next-decision rule

At every Prio cycle, recompute this priority from latest main, real issues/PRs and measured M1; pursue the first **executable** #1 migration slice, not an indefinite research plan. Preserve in-flight PRs for a safe Merge handoff; do not create duplicate owner branches. If a specific native API cannot yet be used, record its exact missing capability in #359 and work on the Rust fix or the next independent #1 slice. Only promote #2/#3 above #1 on a demonstrated blocker or explicit owner reprioritization.

**Hygiene:** replace superseded status, stale PR heads and obsolete instructions in place; keep history in Git/issues, not this file. No new acceptance gates and no manual M1 ledger changes.
