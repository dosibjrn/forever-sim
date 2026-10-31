# Issue #28 — real gsim 2D ↔ pinned native Go range loop (NOT combat ACK)

Complements merged [PR #47](https://github.com/dosibjrn/mage-level-sim/pull/47) on fresh main. The Python `GsimGoRangeFeed` serializes snapshots from a **real gsim `CombatRuntime`** with 2D positions and live target movement, not caller JSON. The new `ingress/` Go program (additive source overlay, copied into pinned native module) consumes those JSONL ticks in **one** `core.NewSim/Reset/PrePull` simulation. Each tick calls `WorldBoundarySession.AdvanceToWorldTick()` then `ApplyWorldDistance()`; the native program immediately writes a JSON receipt. The Python controller validates receipt identity/range/clock/hash echo before advancing the same gsim runtime. The Go process must keep the same PID across all 20 requested ticks.

## Run when pinned upstream Go dependencies are available

The workflow `.github/workflows/wf-gsim-go-native-range-loop.yml` pins `sage3648/mythicsim-forever-engine-go@a667dce8492bd9fb94269a9f864289cb74006775`, copies the already merged PR #47 `world_boundary/core/*.go` overlay and this PR's `world_boundary/ingress/*.go` into it, and builds `cmd/wf_gsim_go_world_ingress`. Then from this project root:

```bash
python tools/wf_gsim_go_live_range_probe.py \
  --binary /path/to/gsim-go-world-ingress \
  --request /path/to/upstream/sim/paladin/retribution/testdata/lights_vigil_request.json \
  --out evidence/gsim-go-range-only.json
```

This smoke uses a genuine moving gsim 2D encounter (selected enemy approaches 20 → 15 yards after one second), but the **native Go request is Paladin** and gsim actor is a minimal world fixture, **not** source-verified Druid L60 Balance. The status is deliberately `RANGE_BIDIRECTIONAL_NOT_SPELL_ACTION_CAUSALITY` and the report always records `native_spell_action_ack=false`, `checkpoint_certified=false`. A world SHA echoed by Go attests the received input identifier, **not independent proof that the input originated in gsim**: provenance is tied to the Python process's actual `CombatRuntime`.

Local source checks (Go 1.23): `GO111MODULE=off go test -count=1 feed.go feed_test.go` PASS (3 tests), `go vet feed.go feed_test.go` PASS; Python source/test `compileall` PASS; pure 20→15/invalid-input projection smoke PASS. **Full pinned Go build and actual live 2D↔Go execution NOT YET VERIFIED** until runner allocation works (issue #42). No fabricated native score is recorded.

## Protection and current limitations

- All feed ticks carry source snapshot SHA256, explicit `range_only`, a monotonic 1ms clock, unique sequence, player index and source target ID. The Go parser rejects unknown fields, invalid hash, replay/rollback, impossible distance, and any claim of facing/controls/spell ACK or checkpoint PASS.
- Python fails closed on an unacknowledged range tick, missing or forged receipt fields, intervening mutation of real gsim world, bad native source/revision/request hash, and native process restart; the sole native Go process is never restarted between ticks.
- **Not yet implemented:** source-legal Druid L60 native request, real native **spell/action identity and outcome**, world-side action application/ACK, facing/CC application, real native decision perturbation, continuous 100-mob recovery, or any live P7 gate. Range receipts are **not** native spell/action ACKs and their JSON fields can be fabricated in isolation. **0/148** remains unchanged.

## Next executable increment

1. Once the exact pinned native binary runs, obtain actual coupled raw trace, native request/source/binary hashes, live gsim world hashes and PID, and inspect the real 20-tick response; never call a zero-step CI run PASS/FAIL for code.
2. Extend the **same** native Go session with real spell/action IDs plus source-native decisions; apply those actions to the actual gsim world and require world-action ACK before the next decision. Demonstrate a near/far or rooted/unrooted paired **Druid L60 Balance** native outcome difference with identical request/seed/source. Reject post-hoc simulated ACKs and no-op decisions.
3. Feed that genuine causal witness into the PROCESS live gate providers, then work toward full P1–P7 and the 100-mob recovery requirement. Do not change PROCESS or OVERALL PLAN to lower the threshold.

The existing `native_step_protocol.py` describes an independent Rust JSONL transport; this Go path uses its own `gsim-go-range-v1` and deliberately makes no claim of Rust session support.
