// Consume real gsim 2D range ticks in one retained pinned native Go Simulation.
// This does NOT ACK spells, facing or CC and does not certify PROCESS gates.
package main

import (
    "bufio"
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

const pinnedGoRevision = "a667dce8492bd9fb94269a9f864289cb74006775"

type rangeReply struct {
    Type string `json:"type"`
    Sequence uint64 `json:"sequence"`
    ObservedInputWorldSHA256 string `json:"observed_input_world_sha256"`
    NativeRangeReceipt core.WorldRangeReceipt `json:"native_range_receipt"`
    NativeSourceRevision string `json:"native_source_revision"`
    NativeRequestSHA256 string `json:"native_request_sha256"`
    NativeProcessID int `json:"native_process_id"`
    NativeSpellActionACK bool `json:"native_spell_action_ack"`
    CheckpointCertified bool `json:"checkpoint_certified"`
}

func run(requestRaw []byte, sourceRevision string) error {
    if sourceRevision != pinnedGoRevision {return errors.New("PINNED_GO_SOURCE_REVISION_REQUIRED")}
    request := &proto.RaidSimRequest{}
    if err := (protojson.UnmarshalOptions{DiscardUnknown:false}).Unmarshal(requestRaw,request);err!=nil {return err}
    if request.Raid==nil || request.SimOptions==nil || request.Encounter==nil {return errors.New("NATIVE_REQUEST_MISSING_SIM_COMPONENTS")}
    sim.RegisterAll()
    native:=core.NewSim(request,simsignals.CreateSignals())
    native.Reset()
    native.PrePull()
    boundary,err:=core.NewWorldBoundarySession(native)
    if err!=nil {return err}
    reqHash:=sha256.Sum256(requestRaw)
    writer:=bufio.NewWriter(os.Stdout)
    scanner:=bufio.NewScanner(os.Stdin)
    scanner.Buffer(make([]byte,64*1024),2*1024*1024)
    validator:=&tickValidator{}
    count:=0
    for scanner.Scan() {
        if count>=10000 {return errors.New("WORLD_TICK_LIMIT_EXCEEDED")}
        tick,err:=decodeWorldTick(scanner.Bytes())
        if err!=nil {return fmt.Errorf("tick %d parse: %w",count,err)}
        if err:=validator.validate(tick);err!=nil {return fmt.Errorf("tick %d validate: %w",count,err)}
        if _,err:=boundary.AdvanceToWorldTick(time.Duration(tick.NativeClockNS),200000);err!=nil {return fmt.Errorf("tick %d native advance: %w",count,err)}
        receipt,err:=boundary.ApplyWorldDistance(tick.Sequence,tick.NativePlayerIndex,tick.DistanceYards)
        if err!=nil {return fmt.Errorf("tick %d native range apply: %w",count,err)}
        if receipt.Sequence!=tick.Sequence || receipt.NativeClockNS!=tick.NativeClockNS || receipt.AppliedYards!=tick.DistanceYards || receipt.PlayerIndex!=tick.NativePlayerIndex {
            return errors.New("NATIVE_RANGE_RECEIPT_MISMATCH")
        }
        reply:=rangeReply{Type:"native_go_range_receipt",Sequence:tick.Sequence,
            ObservedInputWorldSHA256:tick.WorldSHA256,NativeRangeReceipt:receipt,
            NativeSourceRevision:sourceRevision,NativeRequestSHA256:hex.EncodeToString(reqHash[:]),NativeProcessID:os.Getpid(),
            NativeSpellActionACK:false,CheckpointCertified:false}
        output,err:=json.Marshal(reply)
        if err!=nil {return err}
        if _,err:=writer.Write(append(output,'\n'));err!=nil {return err}
        if err:=writer.Flush();err!=nil {return err}
        count++
    }
    if err:=scanner.Err();err!=nil {return err}
    if count==0 {return errors.New("NO_GSIM_WORLD_TICKS_RECEIVED")}
    return nil
}

func main() {
    requestPath:=flag.String("request","","pinned upstream RaidSimRequest JSON")
    sourceRevision:=flag.String("source-revision","","pinned Go source SHA")
    flag.Parse()
    raw,err:=os.ReadFile(*requestPath)
    if err==nil {err=run(raw,*sourceRevision)}
    if err!=nil {fmt.Fprintln(os.Stderr,err);os.Exit(1)}
}
