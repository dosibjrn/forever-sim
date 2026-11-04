# First complete checkpoint target: druid:L60:balance

> **Historical plan note (2026-11-03):** P1/P2 were retired by owner-approved PROCESS v2.20. This document's former P1/P2 run instructions are superseded; active acceptance is P3–P6 and P7.1–P7.5 only.

This work is the vertical slice toward **0/148 → 1/148**, not a claim that the
checkpoint is accepted. The canonical approval contract is [PROCESS v2.20](../../../PROCESS.md),
not a historical six-gate release or a native-only diagnostic.

## Verified initial inventory (2026-10-30)

- Already on main: real P7.1 native Rust reference reproduction explicitly
  accepted by the owner: **728.1936126415858 DPS / 10,000 iterations**.
  Source: `docs/evidence/druid-l60-balance/p7.1/`, `docs/WORKER.md`.
  The owner's legacy acceptance is respected. It does *not* prove live 2D.
- PR #25 merged: independent Rust-only P7.5 joint search, 807.9191412484101
  4,000-fight frozen holdout mean. The PR explicitly records that this is NOT
  formal coupled P7.5 acceptance.
- The former P1/P2 Python providers are historical diagnostics only. Their Druid L60 runs are not part of current checkpoint acceptance and must not be scheduled or recorded.
- The public gate CLI dispatches P3–P6 and P7.1–P7.5 to modules
  `tools.wf_gate_<gate>_live`. Those modules did not exist on main at
  the start of this work: **BLOCKED: LIVE_GATE_RUNNER_MISSING**.
  Native-only optimizers are not equivalent providers.
- The pinned external Rust `forever-engine` main CLI publicly implements
  `sim`, `prepare`, `check`, `bench`, `version`. No live incremental
  world-boundary/ACK session was found. A subprocess one-shot `sim` run at
  every world tick would reset native combat state; it is prohibited as proof
  of continuous gsim↔Rust causality.
- Native P7.5 still needs the accepted comparable prior (issue #29) and any
  actual winning item/ability effect gaps (issue #30). Don't invent a new
  source-attestation gate.

## Retired diagnostic wrappers (2026-11-04)

The one-off `tools/wf_checkpoint_druid_balance_l60.py` and `tools/wf_native_session_capability.py` scripts have been retired. The checkpoint wrapper still expected the former P1/P2 gates (11 results total), while the canonical `tools/wf_gate.py` now exposes only the nine active P3–P6 and P7.1–P7.5 gates. The session script performed only a JSONL handshake; it did not execute a live gsim 2D action/ACK trace or certify a gate. Neither wrapper is part of current acceptance.

Use the stable gate CLI directly for an individual active gate, for example:

```bash
python tools/wf_gate.py --class druid --level 60 --spec balance --gate P3
```

Select P4–P6 or P7.1–P7.5 as appropriate. A CLI report does not certify a checkpoint by itself; only genuine gate results and Merge-owned M1 integration change acceptance records.

## New transport component (not yet a coupled simulator)

`src/game/runtime/native_step_protocol.py` is a single-stateful-process
JSONL boundary transport. A new `snapshot_gsim_world(runtime)` captures actual `CombatRuntime` moving target coordinates, control expiration state, selected target and live clock; its tests demonstrate that a real approaching enemy changes the snapshot hash, and reject invented JSON as a controller. This remains observation-only: no real native combat action is applied yet. The native process must announce the protocol and
session ID. Every world boundary includes the monotonic clock, actual world
snapshot hash, and prior world-action ACK. Native must echo the world hash and
ACK ID, returning an action ID and decision. The world must apply that action
and ACK **before** another boundary. A missing step-capable native process,
one-way trace, wrong state hash, missing ACK, backwards clock or process
restart fails closed. Tests use a toy subprocess only for **transport unit
tests**, never as combat/gate evidence.

Still missing: implement the corresponding incremental **Rust engine-owned**
combat session against the real `forever-engine` scheduler; wire a real gsim
2D controller (coordinates, facing, range, movement, CC, target non-aggression)
to world snapshots and ACK application; demonstrate the perturbation changes a
later native combat decision; execute P7 measurements and genuinely continuing
100-mob P4–P6 with shared actor resources and full legality. No synthetic or
post-hoc trace may count. Native work may require a writable fork or accepted
contributions to `sage3648/mythicsim-forever-engine`, where this GitHub
connection currently has read-only permission.

## Promotion

No change to 0/148 here. When every gate has genuinely passed on compatible
current source/engine semantics and their independent evidence is reviewed,
the integrator can promote **one** checkpoint. The audit runner itself never
certifies a checkpoint.
