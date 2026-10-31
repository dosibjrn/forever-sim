// A real pinned MythicSim Go scheduler-step feasibility probe for issue #28.
// Build from the checked-out upstream Go module; this is NOT a 2D/ACK bridge.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/wowsims/forever/sim"
	"github.com/wowsims/forever/sim/core"
	"github.com/wowsims/forever/sim/core/proto"
	"github.com/wowsims/forever/sim/core/simsignals"
	"google.golang.org/protobuf/encoding/protojson"
)

const pinnedGoRevision = "a667dce8492bd9fb94269a9f864289cb74006775"

type stepReport struct {
	Kind                  string            `json:"kind"`
	Status                string            `json:"status"`
	Reason                string            `json:"reason,omitempty"`
	Engine                string            `json:"engine"`
	SourceRevision        string            `json:"source_revision"`
	BinarySHA256          string            `json:"binary_sha256"`
	RequestSHA256         string            `json:"request_sha256"`
	NativeStepsExecuted   int               `json:"native_steps_executed"`
	NativeDamageTaken     float64           `json:"native_damage_taken"`
	Samples               []stepObservation `json:"native_step_samples"`
	NativeSessionReused   bool              `json:"native_session_reused"`
	Gsim2DWorldApplied    bool              `json:"gsim_2d_world_applied"`
	NativeWorldActionACK  bool              `json:"native_world_action_ack"`
	Full100MobRunExecuted bool              `json:"full_100mob_run_executed"`
	CheckpointCertified   bool              `json:"checkpoint_certified"`
}

func sha256File(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	h := sha256.New()
	if _, err := io.Copy(h, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func runProbe(raw []byte, report *stepReport, maxSteps int, requireDamage bool) error {
	if maxSteps < 2 || maxSteps > 1000000 {
		return errors.New("INVALID_NATIVE_STEP_BUDGET")
	}
	request := &proto.RaidSimRequest{}
	if err := (protojson.UnmarshalOptions{DiscardUnknown: false}).Unmarshal(raw, request); err != nil {
		return fmt.Errorf("INVALID_PINNED_GO_REQUEST: %w", err)
	}
	if request.SimOptions == nil || request.Raid == nil || request.Encounter == nil {
		return errors.New("NATIVE_RAID_SIM_REQUEST_INCOMPLETE")
	}
	// Register real class implementations before constructing the actual
	// Go combat engine. One Simulation object is retained for every Step.
	sim.RegisterAll()
	native := core.NewSim(request, simsignals.CreateSignals())
	native.Reset()
	native.PrePull()
	snapshot := func(step int) stepObservation {
		return stepObservation{Step: step, ClockNS: int64(native.CurrentTime),
			DamageTaken: native.Encounter.DamageTaken}
	}
	start := snapshot(0)
	previous := start
	report.Samples = append(report.Samples, start)
	finished := false
	for i := 1; i <= maxSteps; i++ {
		finished = native.Step()
		current := snapshot(i)
		if err := validateTransition(previous, current); err != nil {
			return err
		}
		if i <= 8 || i%1000 == 0 {
			report.Samples = append(report.Samples, current)
		}
		report.NativeStepsExecuted = i
		previous = current
		if finished {
			break
		}
	}
	if report.Samples[len(report.Samples)-1].Step != previous.Step {
		report.Samples = append(report.Samples, previous)
	}
	report.NativeDamageTaken = previous.DamageTaken
	if err := validateCompletedTrace(start, previous, report.NativeStepsExecuted, finished); err != nil {
		return err
	}
	if requireDamage && previous.DamageTaken <= start.DamageTaken {
		return errors.New("NATIVE_COMBAT_DAMAGE_NOT_OBSERVED")
	}
	report.NativeSessionReused = true
	report.Status = "NATIVE_GO_SINGLE_FIGHT_SCHEDULER_STEPS_OBSERVED"
	return nil
}

func main() {
	requestPath := flag.String("request", "", "pinned upstream protojson RaidSimRequest")
	sourceRevision := flag.String("source-revision", "", "actual pinned Go checkout revision")
	outputPath := flag.String("out", "", "optional JSON evidence output")
	maxSteps := flag.Int("max-steps", 200000, "maximum actual native scheduler Step calls")
	requireDamage := flag.Bool("require-damage", true, "require observable native encounter damage")
	flag.Parse()

	report := stepReport{Kind: "pinned_go_scheduler_step_probe_v1", Status: "NOT_YET_VERIFIED",
		Engine: "msim-go", SourceRevision: *sourceRevision,
		Gsim2DWorldApplied: false, NativeWorldActionACK: false,
		Full100MobRunExecuted: false, CheckpointCertified: false}
	var err error
	if *requestPath == "" || *sourceRevision != pinnedGoRevision {
		err = errors.New("PINNED_GO_REQUEST_AND_EXACT_SOURCE_REVISION_REQUIRED")
	} else {
		var raw []byte
		raw, err = os.ReadFile(*requestPath)
		if err == nil {
			digest := sha256.Sum256(raw)
			report.RequestSHA256 = hex.EncodeToString(digest[:])
			var executable string
			executable, err = os.Executable()
			if err == nil {
				report.BinarySHA256, err = sha256File(executable)
			}
			if err == nil {
				err = runProbe(raw, &report, *maxSteps, *requireDamage)
			}
		}
	}
	if err != nil {
		report.Reason = err.Error()
	}
	data, marshalErr := json.MarshalIndent(report, "", "  ")
	if marshalErr != nil {
		fmt.Fprintln(os.Stderr, marshalErr)
		os.Exit(2)
	}
	data = append(data, '\n')
	if *outputPath != "" {
		if writeErr := os.WriteFile(*outputPath, data, 0644); writeErr != nil {
			fmt.Fprintln(os.Stderr, writeErr)
			os.Exit(2)
		}
	}
	fmt.Print(string(data))
	if err != nil {
		os.Exit(1)
	}
}
