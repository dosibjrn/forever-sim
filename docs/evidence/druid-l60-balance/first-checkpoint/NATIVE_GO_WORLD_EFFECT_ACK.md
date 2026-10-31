# WF #28 — source-native spell damage → real gsim world application → native ACK

**Scope:** first **damage-only single-player/single-enemy** Go↔gsim world-action feedback seam. This is a partial implementation of issue #28, not a Druid L60 Balance P7.1–P7.5 certificate or a 100-mob leveling evaluator.

## Why it is not another cumulative metrics report

The prior #58 logic reads `Spellbook/SpellMetrics` counters only; these lack exact event times. The new hook is deliberately placed **inside the real pinned** `sim/core/spell_result.go` `Spell.dealDamageInternal`. `patch_native_spell_result.py` refuses any source not matching upstream Git blob **`f196a60831571c2ff2ccf536aabe17cfa873b5ea`** from `sage3648/mythicsim-forever-engine-go@a667dce8492bd9fb94269a9f864289cb74006775`. It adds exactly one `recordWorldDamageForGsim` call without changing the native spell calculation. The source file and unique anchor were independently read from that exact commit. The runtime code uses `SpellResult.Damage`, native simulation time, real source ActionID/rank, source-native enemy index/unit index/label, critical-hit and periodic flags.

The Go `WorldBoundarySession` journal only registers after one `core.NewSim/Reset/PrePull` and persists across ticks; it never invents an event when a spell was merely registered or from a DPS sum. It rejects invalid source damage, chronology regression and ambiguous enemy targets. When a native world tick is processed, the ingress returns **the actual event list** with the range receipt, then **does not advance the native scheduler again** until a matching gsim world ACK arrives.

## Source-checked acknowledgment sequence

1. Python `GsimGoRangeFeed` snapshots a real `CombatRuntime` 2D world and sends `gsim_world_range_tick` with source hash, selected target, native clock and previous native-accepted ACK ID.
2. One pinned native Go session advances with the supplied range, emits recorded native spell damage events (event ID, nanosecond time, native enemy target ID, source spell/rank, damage) and its independent cumulative spell metrics.
3. Python `GsimNativeDamageWorldApplier` validates the **real gsim world hash** and native event IDs/clock/source target, applies **exact native event damage to `TargetState.apply_damage`**, measures the actual target HP difference and new gsim world hash, and sends `gsim_native_damage_applied_ack` with *all* native event IDs, both hashes, native PID and exact applied damage.
4. Go compares those IDs and damage totals against its own genuine source journal and its pending world tick, verifies the PID, timestamp, source hash and actual-world-changed condition, and returns `native_go_world_ack_accepted` with an ACK ID bound to the event list. The **next** world tick must echo that exact ACK ID before another native combat scheduler advance.
5. Missing/replayed/forged ACK or wrong damage, event ID, PID, world hash, timestamp, sequence or process restart fails closed. Empty event batches receive an explicit no-action ACK but never masquerade as spell action proof.

## Tests and evidence

**Verified locally on identical GitHub blobs:**
- `world_damage_ack.go` blob `fb2ad0cbd40c4baf30d18dd4cabeab3cad44d757` and `world_damage_ack_test.go` blob `7e69b3c026b68f832d8e171ead330161faf21b7a`. `GO111MODULE=off go test -count=1 -v feed.go feed_test.go world_damage_ack.go world_damage_ack_test.go`: **7 PASS**. `go vet`: **PASS**. The locally formatted older `feed*.go` has equivalent content but different blob hashes.
- `patch_native_spell_result.py` blob `8b33f35abf1241bf018733a41626adb9d8b7555c`, its unit test blob `368606253a27bd76a5a5e625d61e2f16815634d4`; **2 PASS** for wrong-source and exactly-once source hook installation.
- Existing native spell counter / native-target identity focused Python tests, alongside hook tests: **25 PASS** locally; most local supporting Python source files were not all byte-identical to the GitHub head. This is **not whole-head tested native Go evidence**.

**NOT YET VERIFIED**: exact pinned native-Go full compilation after the source hook, real `Spell.dealDamageInternal` firing in one pinned Go binary, real gsim target damage effect followed by native ACK, near/far native action outcome difference, source-matched Druid L60 Balance. GitHub Actions jobs have repeatedly failed **with zero runner steps** (#42), so no actual native Go execution verdict is available. No fabricated measured DPS or claimed end-to-end PASS.

## Known semantic limits — do not certify P7

- This is a **damage-only, one-player/one-native-enemy** seam; pets, healing, buffs, debuffs, CC, facing, target retarget and full gsim/native HP/aggro parity are not yet unified.
- Native exact event time is captured, but the first harness applies each event to gsim at the **next world tick**, with nonzero tick granularity, not necessarily precisely at its native event time. This must be refined or bounded for strict production P7 world semantics.
- Diagnostic upstream native fixture is **Paladin** while gsim uses a minimal moving 2D world. It is not source-matched Druid L60 Balance and not proof the *same* legal spell/gear/talent encounter was used.
- An ACK verifies the native event list against a world hash *measured by the gsim controller process*. It does not magically make external arbitrary JSON a trusted gsim world. The Python side refuses non-`CombatRuntime` controllers and uses actual target HP deltas.
- 100 consecutive mobs with paid recovery (#61) and all P1–P7.5 gates are still separate requirements. **0/148 unchanged**.

**Next action:** independently build and run the exact pinned overlay + 20 ticks + 3/80 yd paired scenarios on a working runner or writable upstream checkout. Preserve raw native JSONL effects, ACK IDs, world hashes, PID, binary SHA, request/seed and test output. Then replace minimal Paladin fixture with Druid L60 Balance source-matched input, implement other world effect types and tick-accurate causality, and connect the same interface to #61 persistent recovery.

## Source-native ACK v2 hardening (2026-10-31)

The first ACK validator checked ordered native event IDs and summed damage, but not the echoed action/rank, enemy unit/label, native time, or crit/periodic/landed flags. The new required `applied_events` list is compared **field-for-field** with native Go journal events before a world ACK can be accepted. The subsequent `ACKID` now commits to the **full native event list**, world before/after hashes, PID and tick sequence (`gsim-native-ACK-v2`, SHA256). The Python gsim applier echoes the exact native event metadata only after validating the real measured target HP change.

**Exact-byte local evidence:** checked GitHub blob IDs `world_damage_ack.go=8392076c8b7af8e7d38ff21a192541b649ee790a` and `world_damage_ack_test.go=8149df30b5a55ad3b32392dce1b060fa752759e4`. Executed `GO111MODULE=off go test -count=1 -v world_damage_ack.go world_damage_ack_test.go stub_test.go`: **5/5 Go test functions PASS**; `go vet` PASS. The `stub_test.go` file supplies ONLY `worldTick` and `goodTick`, not native combat. Python `go_native_world_damage_ack.py` blob `e7d3fe25a98638d3c776916ff2681f1632e34364` passed **15 isolated local Python fake-runtime tests** for HP/hash application, metadata tampering, overkill, duplicate event and target-identity mismatch; not an authentic full gsim run.

**Important: not yet verified** is an actual pinned Go engine build with source callback, true Go↔gsim process execution, a causal paired native spell outcome, or a matched Druid L60 Balance trial. GitHub Actions still fails before job steps (#42). All full P1–P7.5 checkpoints **0/148**.

