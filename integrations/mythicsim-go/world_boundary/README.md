# Pinned Go world-range boundary overlay — issue #28 (partial)

This is an **additive source overlay** for the pinned `sage3648/mythicsim-forever-engine-go@a667dce8492bd9fb94269a9f864289cb74006775` engine. The CI workflow copies the `core/*.go` files into its real `sim/core` package, then compiles and runs the `probe/main.go` command in the same upstream module. The original upstream repository is not changed.

`WorldBoundarySession` retains **one real native `core.Simulation`**, steps only native events strictly *before* the next world tick (including auto-attack and task queues), parks the native clock at the tick, and requires exactly one range application before proceeding. An event at exactly the world tick must observe the newly applied range. Distance is written into the real `Unit.DistanceFromTarget` used by native spell range conditions, with native movement and auto-attack conflict handling. A receipt contains actual native clock, sequence, applied range and accumulated encounter damage.

## Evidence and strict limitations

- Locally executable on Go 1.23 without upstream dependencies: `go test -count=1 -v core/boundary_logic.go core/boundary_logic_test.go` and `go vet core/boundary_logic.go core/boundary_logic_test.go`.
- The full overlay, native core unit tests and probe require the pinned upstream module and Go toolchain; see `.github/workflows/go-world-boundary-overlay.yml`. They are **NOT YET VERIFIED** until the real runner executes. A zero-step runner allocation failure (issue #42) is not a code test failure.
- The probe uses a real upstream Paladin request and a **constant external distance**, **not** a gsim 2D snapshot. A native range receipt is **not** a native spell action/ACK. This PR does **not** demonstrate a world perturbation changing a subsequent native spell decision, nor Druid L60 Balance, facing, CC, native world-action ACK, continuous 100-mob recovery, or any P1–P7 PASS. Checkpoint count remains 0/148.
- No fake damage, mock native engine, or post-hoc action receipt is used. Do not promote any PROCESS gate from this smoke.

**DO next (issue #28, implementation worker):** connect real gsim `CombatRuntime` world snapshots to `ApplyWorldDistance`, instrument native spell/action identity and gsim application ACK, and run paired Druid Balance L60 near/far perturbations with a pinned executable. Acceptance: identical source/seed/scenario, one retained native simulation per run, an actual gsim world tick and ACK preceding the next native action, and a measured native decision or damage delta; fail closed if no causality. The integrator owns review/merge, not this implementation branch.
