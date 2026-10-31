# Go native scheduler-step feasibility — issue #28

This is a **real Go-engine scheduler-step probe**, not a coupled 2D combat
implementation or a P1–P7 acceptance artifact. It is a separate, additive
implementation branch because PR #33 owns the Rust transport and first
checkpoint audit; do not edit or merge that branch here.

## Pinned source and executable path

- Source: `sage3648/mythicsim-forever-engine-go` at
  `a667dce8492bd9fb94269a9f864289cb74006775` (the same Go revision as
  `.github/workflows/build-pinned-engines.yml`).
- The source has exported `core.NewSim`, `Simulation.Reset`,
  `Simulation.PrePull` and `Simulation.Step`. Unlike repeated `wowsimcli
  sim` calls, `Step` can advance one **persisted native Simulation**.
- The smoke uses the **upstream** saved
  `sim/paladin/retribution/testdata/lights_vigil_request.json` with strict
  `protojson` parsing; no invented scores or generated fake combat inputs.
- CI copies this command into the pinned upstream Go module, generates
  protobuf bindings, builds the real engine, and executes scheduler steps
  against that fixture. It saves exact request/binary SHA256, step count,
  monotonic native clock and accumulated native damage. The evidence includes
  `gsim_2d_world_applied=false`, `native_world_action_ack=false` and
  `checkpoint_certified=false` **even when the smoke succeeds**.

Example after building the pinned Go module and copying `step_probe` into
`upstream/cmd/wf_step_probe`:

```sh
cd upstream
go test ./cmd/wf_step_probe -count=1
go build -trimpath -o ../go-step-probe ./cmd/wf_step_probe
cd ..
./go-step-probe --request upstream/sim/paladin/retribution/testdata/lights_vigil_request.json \
  --source-revision a667dce8492bd9fb94269a9f864289cb74006775 \
  --out go-step.json
```

## Evidence and remaining implementation

The five standalone standard-library Go regression tests for the transition
validator were locally executed on Go 1.23.2 (RED before implementation,
GREEN afterward). **That is not proof that the Go 1.25.4 upstream binary
compiles or that native combat ran.** Actual pinned-engine execution awaits
the dedicated Actions job; GitHub Actions runner allocation currently fails
before steps begin (issue #42).

**DO issue #28 Go world-boundary injection FIRST** (implementation owner):
extend the pinned Go scheduler behind an actual interactive world-boundary
interface with native action identity and applied-world ACK, preserving one
simulation instance. Implement the adapter to PR #33's real
`gsim.CombatRuntime` snapshot, enforce a shared clock without stepping past
the world boundary, and prove a paired world perturbation changes a later
**native** action/damage result. Verify on a pinned Druid Balance L60 fixture
with a real 2D controller, not this Paladin scheduler-only smoke. If the Go
engine cannot pause or consume the needed world inputs without patching
upstream, implement a narrowly reviewed source overlay or request a writable
upstream fork. Never call this probe a native 2D PASS.

CI-execution **BLOCKED** means the GitHub runner does not start
(`runner_id=0, steps=[]`); it does not make this code or the next source
implementation inherently blocked. Current checkpoint count remains 0/148.
