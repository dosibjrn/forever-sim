# WF444 — joint sampled physical critical damage + resource proc (P2 WIP)

**Parent:** `WF443_DRUID_L30_P2_MERGED_129_RANK_WIP_ON_WF441.zip`, SHA256 `2adbc97106d8b63a8da9dcd46ace32fbc299f6b070c414825d1d4eb228fde52b`. This is a *three-file code delta on WF443 only*, not a new FULL baseline or a P2 certificate. WF443 supersedes BOTH parallel WF442 branches; do not apply WF442 first. No SQLite changes.

## Material runtime change

`critical_resource_gain` modifiers now compile a generic source-typed sampled `nonperiodic_melee_critical` rule. When an active rule is eligible, CombatRuntime uses a deterministic event-scoped hit/crit draw for the **same outgoing physical Damage event**, replacing its expected damage with the realized miss/hit/crit damage. A second event-scoped draw determines whether the sourced conditional resource proc occurs; resource gain is discrete (0 or the sourced full amount), never fractional Combo Points. The `sampling_seed` constructor parameter controls deterministic replay. Rules without this explicit resolution preserve existing expected-value behavior. Source-specific names/numeric mechanics remain in GameIR; no class/spell/talent ID branch added.

Covered synthetic real-runtime paths: auto-attack with miss/hit/crit and Rage proc; action `DamageEffect` with critical multiplier and source `ResourceChangeEffect` generator and Combo proc; deterministic seeds, probabilistic proc, baseline expected-value preservation, generic modifier-to-rule compilation. The direct-damage event now exposes its source crit multiplier.

## TDD evidence

- First RED: 4 FAIL / 0.22s (after fixture correction); GREEN 4 PASS / 0.32s.
- Second RED: 1 FAIL, 4 PASS / 0.22s (direct physical action did not carry crit multiplier); GREEN 5 PASS / 0.21s.
- REFACTOR: 17 PASS, 1 deselected / 0.28s. Additional auto-attack outcome regression 1 PASS / 0.23s.
- Wider suite: TIMEOUT / NOT PASS. Historical G27 source-text test was corrected by deleting class name from a comment; a separate historical `schema_version == 16` assertion fails against WF443's schema 17. This is not evidence of a new schema regression.
- Full source-bound P2 test is **NOT RUN TO COMPLETION**: partial reconstruction lacks intermediate source overlays. Restoring original WF392 atom parser+attestation advanced the test to `P2_GAME_IR_NOT_BOUND_TO_PINNED_SOURCE:improved_wrath`. Do not treat that reconstruction failure as a fresh 70338 source observation.
- Staged SQLite SHA256 unchanged: `4f7cf12a96d9c1704e57e249b4cb13719749df7a7252f4872812cb0dd8453a4c`; integrity `ok`.
- 40-swing microbenchmark (50 repeats, median): expected legacy 1.6176ms; sampled joint 1.5954ms; same runtime. These are synthetic mechanism costs, not P4 proxy timings or search performance.

## Checkpoint and blockers

**0/148 accepted** per latest WF443 evidence. Druid L30 P2 remains RED: 129/129 structurally reachable ranks have executors, but WF443 recorded 14 partial semantic ranks and one source prerequisite/curve bridge. This work does NOT certify the Blood Frenzy source amount bridge from 70374 to 70338; the existing P2 unsupported flag is deliberately retained. Neither incoming Dodge/Rage nor spell crit haste is yet coupled to the same sampled damage outcome. Multiple targets, 100mob, full P2, P3, P4, P5, P6 and historical held-out comparison were NOT re-certified.

## Rebase and NEXT

Before integration, reconstruct the *complete* published optimizer chain WF309 full + correctly ordered cumulative overlays through WF438, then WF439→WF440→WF441→WF443 (WF442 replaced by WF443). Verify overlapping files against exact parent hashes. The local synthetic tests alone cannot certify source-stage parity because intermediate overlays were not all materialized in this run. **NEXT:** source-bound replay of Blood Frenzy R1/R2 in full pinned 70338 GameIR with 100 consecutive mobs and both forms; then resolve the source amount bridge before removing any P2 partial flag.
