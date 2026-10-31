// A pinned native-Go world-range boundary smoke. This does NOT run gsim 2D,
// capture native spell action IDs, or certify any PROCESS gate.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/wowsims/forever/sim"
	"github.com/wowsims/forever/sim/core"
	"github.com/wowsims/forever/sim/core/proto"
	"github.com/wowsims/forever/sim/core/simsignals"
	"google.golang.org/protobuf/encoding/protojson"
)

const pinnedRevision = "a667dce8492bd9fb94269a9f864289cb74006775"

type sample struct {
	Steps   int                    `json:"native_steps_before_tick"`
	Receipt core.WorldRangeReceipt `json:"native_range_receipt"`
}
type report struct {
	Kind                    string   `json:"kind"`
	Status                  string   `json:"status"`
	SourceRevision          string   `json:"source_revision"`
	RequestSHA256           string   `json:"request_sha256"`
	Samples                 []sample `json:"samples"`
	NativeSessionReused     bool     `json:"native_session_reused"`
	NativeWorldRangeApplied bool     `json:"native_world_range_applied"`
	Gsim2DWorldApplied      bool     `json:"gsim_2d_world_applied"`
	NativeSpellActionACK    bool     `json:"native_spell_action_ack"`
	CheckpointCertified     bool     `json:"checkpoint_certified"`
}

func run(raw []byte, revision string, yards float64, ticks int) (report, error) {
	out := report{Kind: "pinned_go_world_range_boundary_smoke_v1", Status: "NOT_YET_VERIFIED", SourceRevision: revision,
		Gsim2DWorldApplied: false, NativeSpellActionACK: false, CheckpointCertified: false}
	if revision != pinnedRevision {
		return out, errors.New("PINNED_SOURCE_REVISION_REQUIRED")
	}
	if ticks < 2 || ticks > 1000 {
		return out, errors.New("INVALID_WORLD_TICK_COUNT")
	}
	sum := sha256.Sum256(raw)
	out.RequestSHA256 = hex.EncodeToString(sum[:])
	request := &proto.RaidSimRequest{}
	if err := (protojson.UnmarshalOptions{DiscardUnknown: false}).Unmarshal(raw, request); err != nil {
		return out, err
	}
	if request.SimOptions == nil || request.Raid == nil || request.Encounter == nil {
		return out, errors.New("INCOMPLETE_NATIVE_REQUEST")
	}
	sim.RegisterAll()
	native := core.NewSim(request, simsignals.CreateSignals())
	native.Reset()
	native.PrePull()
	boundary, err := core.NewWorldBoundarySession(native)
	if err != nil {
		return out, err
	}
	for i := 0; i < ticks; i++ {
		at := time.Duration(i) * 100 * time.Millisecond
		steps, err := boundary.AdvanceToWorldTick(at, 200000)
		if err != nil {
			return out, fmt.Errorf("tick %d advance: %w", i, err)
		}
		receipt, err := boundary.ApplyWorldDistance(uint64(i), 0, yards)
		if err != nil {
			return out, fmt.Errorf("tick %d apply: %w", i, err)
		}
		if receipt.NativeClockNS != int64(at) || receipt.AppliedYards != yards || receipt.Sequence != uint64(i) {
			return out, errors.New("NATIVE_RANGE_RECEIPT_MISMATCH")
		}
		out.Samples = append(out.Samples, sample{Steps: steps, Receipt: receipt})
	}
	out.NativeSessionReused = true
	out.NativeWorldRangeApplied = true
	out.Status = "NATIVE_GO_RANGE_BOUNDARIES_OBSERVED_NOT_GSIM_2D"
	return out, nil
}

func main() {
	path := flag.String("request", "", "real pinned upstream RaidSimRequest JSON")
	revision := flag.String("source-revision", "", "exact Go source SHA")
	yards := flag.Float64("yards", 30, "external world distance in yards; not a gsim snapshot")
	ticks := flag.Int("ticks", 20, "100ms world ticks")
	out := flag.String("out", "", "optional JSON output")
	flag.Parse()
	raw, err := os.ReadFile(*path)
	var result report
	if err == nil {
		result, err = run(raw, *revision, *yards, *ticks)
	}
	if err != nil {
		result.Status = "NOT_YET_VERIFIED"
		fmt.Fprintln(os.Stderr, err)
	}
	data, marshalErr := json.MarshalIndent(result, "", "  ")
	if marshalErr != nil {
		fmt.Fprintln(os.Stderr, marshalErr)
		os.Exit(2)
	}
	data = append(data, '\n')
	if *out != "" {
		if e := os.WriteFile(*out, data, 0644); e != nil {
			fmt.Fprintln(os.Stderr, e)
			os.Exit(2)
		}
	}
	fmt.Print(string(data))
	if err != nil {
		os.Exit(1)
	}
}
