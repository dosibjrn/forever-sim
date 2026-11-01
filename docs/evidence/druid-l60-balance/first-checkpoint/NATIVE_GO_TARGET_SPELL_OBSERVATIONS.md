# WF #28 — native source spell metrics, target identity and paired world perturbation

This is the next **incremental** stage after merged [PR #49](https://github.com/dosibjrn/mage-level-sim/pull/49). The approved goal remains 148/148 certified P1–P7.5 checkpoints; **this PR does not certify one**.

## Actual implementation

- The pinned-Go source overlay reads the **real registered player Spellbook and native SpellMetrics**, summing all splits so a tagged split switch cannot erase prior native results. A second reader requires **exactly one native enemy** and records its real `Unit.Index`, `Unit.UnitIndex`, `Unit.Label` and the spell's per-target hit/cast/tick/damage counters. Metrics directed at the caster or another target are **not** transferred to the enemy. The result uses native source action IDs, not guessed class names.
- Go `world_boundary/ingress/main.go` returns both cumulative native spell counters and one-enemy target-resolved counters after applying each real world range tick to the same retained native Go simulation.
- Python checks counters are monotonic and source identities remain stable across a world tick. It rejects fake boolean counts, NaN, rollback, missing target, unexpected native target switching, and a changed gsim selected target without a corresponding native rebind.
- Paired diagnostics run the same pinned Go request/seed in **near (3 yd)** and **far (80 yd)** genuine gsim 2D source worlds, and compare observed native spell counters. `--require-native-spell-delta` makes **no native difference** an executed diagnostic failure, rather than silently declaring the optimization valid.

## Test and evidence scope

Locally executed isolated Python ledger+single-native-target tests: **23 PASS** with the exact target-ledger+test blobs at `20acc8ac` and `f5194656`; their supporting source-ledger file was a local semantic-equivalent copy, not exact GitHub bytes. Standalone input-protocol Go tests previously: **3 PASS**, `go vet` PASS on a locally formatted copy, not this complete branch's pinned native build. The **whole exact-head** pinned-Go integration, target-specific core regression, paired native spell result and live 20-tick run are **NOT YET VERIFIED**. GitHub-hosted runner allocation remains issue [#42](https://github.com/dosibjrn/mage-level-sim/issues/42), with prior jobs failing before any steps.

## Honest limitations

Native spell counters are native-combat-owned **cumulative snapshots**, not individual timestamped effect events. They are valid observations of action identity/activity but do NOT establish an action→world mutation/ACK. The paired fixture uses a real moving gsim `CombatRuntime` and an upstream native **Paladin** request, **not matched Druid L60 Balance**. Native target index 0 is explicitly enforced, but a source-equivalent production encounter/target binding and direct per-action gsim application are still absent. Never interpret `native_spell_counters_observed` as PASS; **checkpoint count remains 0/148**.

## Next specific executable task

1. Run the exact pinned Go build, source-native world-target counter tests and 20-tick/near-vs-far diagnostic; preserve exact binary SHA, request+seed, raw native counter deltas and CI command logs. Do not infer code failure from zero-step Actions.
2. Add **real native spell effect callbacks** (event time, target, outcome identity) and world-side application, with a native-verified ACK before a subsequent Go combat decision; reject synthetic/replayed ACKs.
3. Re-run the **Druid L60 Balance** same-source/gear/seed paired perturbation under APPROVED PROCESS, then implement the continuous 100-mob/recovery and remaining live gates independently.

**Ownership:** implementation branch only; integration owns WORK_PRIORITY and merging. No sacred document edits.
