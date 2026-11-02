// Consume real gsim 2D range ticks in one retained pinned native Go Simulation.
// Native damage events must be applied in gsim and ACKed BEFORE next tick.
// Facing/CC and source-matched Druid PROCESS evidence are still missing.
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
    NativeSpellCounters []core.WorldNativeSpellCounter `json:"native_spell_counters"`
    NativeActorState core.WorldActorStateSnapshot `json:"native_actor_state"`
    NativeTargetSpellCounters []core.WorldNativeTargetSpellCounter `json:"native_target_spell_counters"`
    NativeDamageEvents []core.WorldNativeDamageEvent `json:"native_damage_events"`
    NativeSpellActionACK bool `json:"native_spell_action_ack"`
    CheckpointCertified bool `json:"checkpoint_certified"`
    NativeWorldHealthFeedbackActive bool `json:"native_world_health_feedback_active"`
    NativeHealthFraction float64 `json:"native_health_fraction"`
    NativeExecutePhase int32 `json:"native_execute_phase"`
    NativeEncounterEndNS int64 `json:"native_encounter_end_ns"`
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
    if err:=boundary.StartWorldDamageJournal();err!=nil {return err}
    defer boundary.CloseWorldDamageJournal()
    reqHash:=sha256.Sum256(requestRaw)
    writer:=bufio.NewWriter(os.Stdout)
    scanner:=bufio.NewScanner(os.Stdin)
    scanner.Buffer(make([]byte,64*1024),2*1024*1024)
    validator:=&tickValidator{}
    count:=0
    previousACKID:=""
    previousWorldTargetDead:=false
    previousWorldTargetID:=""
    previousWorldHealthAfter:=0.0
    previousWorldMaxHealth:=0.0
    for scanner.Scan() {
        if count>=10000 {return errors.New("WORLD_TICK_LIMIT_EXCEEDED")}
        tick,err:=decodeWorldTick(scanner.Bytes())
        if err!=nil {return fmt.Errorf("tick %d parse: %w",count,err)}
        if err:=validator.validate(tick);err!=nil {return fmt.Errorf("tick %d validate: %w",count,err)}
        if tick.PreviousWorldACKID!=previousACKID {return errors.New("WORLD_EFFECT_PREVIOUS_ACK_NOT_ECHOED")}
        if err:=validateWorldTargetTransition(previousWorldTargetID,previousWorldTargetDead,tick.SelectedTargetID);err!=nil {
            return fmt.Errorf("tick %d target transition: %w",count,err)
        }
        if err:=validateWorldHealthContinuity(tick,previousWorldTargetID,
            previousWorldTargetDead,previousWorldHealthAfter,previousWorldMaxHealth,count>0);err!=nil {
            return fmt.Errorf("tick %d world health preflight: %w",count,err)
        }
        if previousWorldTargetID=="" {previousWorldTargetID=tick.SelectedTargetID}
        if previousWorldTargetDead {
            if tick.SelectedTargetID==previousWorldTargetID {
                return errors.New("WORLD_NEXT_TARGET_MUST_DIFFER_FROM_DEAD_TARGET")
            }
            if err:=boundary.BeginNextWorldTarget();err!=nil {
                return fmt.Errorf("tick %d retained native next target: %w",count,err)
            }
            previousWorldTargetDead=false
            previousWorldTargetID=tick.SelectedTargetID
        }
        // The first native action must see gsim's actual starting HP, not
        // a full-health default from the native request. Reinitialize only
        // after a genuine lethal ACK and serial retarget; later ticks use
        // the previous ACK-confirmed health without speculative adjustment.
        if _,_,initialized:=boundary.WorldHealthDecisionSnapshot();!initialized {
            if _,err:=boundary.ApplyWorldTargetHealth(
                tick.WorldTargetHealthBefore,tick.WorldTargetHealthBefore,
                tick.WorldTargetMaxHealth,0);err!=nil {
                return fmt.Errorf("tick %d initial world health: %w",count,err)
            }
        }
        if _,err:=boundary.AdvanceToWorldTick(time.Duration(tick.NativeClockNS),200000);err!=nil {return fmt.Errorf("tick %d native advance: %w",count,err)}
        receipt,err:=boundary.ApplyWorldDistance(tick.Sequence,tick.NativePlayerIndex,tick.DistanceYards)
        if err!=nil {return fmt.Errorf("tick %d native range apply: %w",count,err)}
        if receipt.Sequence!=tick.Sequence || receipt.NativeClockNS!=tick.NativeClockNS || receipt.AppliedYards!=tick.DistanceYards || receipt.PlayerIndex!=tick.NativePlayerIndex {
            return errors.New("NATIVE_RANGE_RECEIPT_MISMATCH")
        }
        targetCounters,err:=boundary.NativeSingleTargetSpellCounters(tick.NativePlayerIndex)
        if err!=nil {return fmt.Errorf("tick %d native target counter read: %w",count,err)}
        spellCounters,err:=boundary.NativeSpellCounters(tick.NativePlayerIndex)
        if err!=nil {return fmt.Errorf("tick %d native spell counter read: %w",count,err)}
        nativeEffects,err:=boundary.DrainWorldDamageEvents()
        if err!=nil {return fmt.Errorf("tick %d native effect journal: %w",count,err)}
        actorState,err:=boundary.WorldActorState(tick.NativePlayerIndex)
        if err!=nil {return fmt.Errorf("tick %d native actor state: %w",count,err)}
        healthFraction,executePhase,healthActive:=boundary.WorldHealthDecisionSnapshot()
        nativeEndNS,err:=boundary.NativeEncounterEndNS()
        if err!=nil {return fmt.Errorf("tick %d native encounter end: %w",count,err)}
        reply:=rangeReply{Type:"native_go_range_receipt",Sequence:tick.Sequence,
            ObservedInputWorldSHA256:tick.WorldSHA256,NativeRangeReceipt:receipt,
            NativeSourceRevision:sourceRevision,NativeRequestSHA256:hex.EncodeToString(reqHash[:]),NativeProcessID:os.Getpid(),
            NativeSpellCounters:spellCounters,NativeActorState:actorState,NativeTargetSpellCounters:targetCounters,
            NativeDamageEvents:nativeEffects,
            NativeSpellActionACK:false,CheckpointCertified:false,
            NativeWorldHealthFeedbackActive:healthActive,NativeHealthFraction:healthFraction,
            NativeExecutePhase:executePhase,NativeEncounterEndNS:nativeEndNS}
        output,err:=json.Marshal(reply)
        if err!=nil {return err}
        if _,err:=writer.Write(append(output,'\n'));err!=nil {return err}
        if err:=writer.Flush();err!=nil {return err}
        // Strict synchronization: don't run another native scheduler event
        // until gsim sends a correctly bound world-effect ACK.
        if !scanner.Scan() {
            if scanner.Err()!=nil {return scanner.Err()}
            return errors.New("WORLD_EFFECT_ACK_MISSING_BEFORE_NEXT_NATIVE_TICK")
        }
        proofs:=make([]sourceNativeEventProof,0,len(nativeEffects))
        for _,effect:=range nativeEffects {
            proofs=append(proofs,sourceNativeEventProof{
                EventID:effect.EventID,NativeTimeNS:effect.NativeTimeNS,
                SourceActionID:effect.SourceActionID,Rank:effect.Rank,
                NativeTargetIndex:effect.NativeTargetIndex,
                NativeTargetUnitIndex:effect.NativeTargetUnitIndex,
                NativeTargetLabel:effect.NativeTargetLabel,
                Damage:effect.Damage,Landed:effect.Landed,
                Crit:effect.Crit,Periodic:effect.Periodic,
                NativeCasterType:effect.NativeCasterType,
                NativeCasterUnitIndex:effect.NativeCasterUnitIndex,
                NativeCasterLabel:effect.NativeCasterLabel,
            })
        }
        accepted,err:=checkWorldEffectACK(scanner.Bytes(),tick,proofs,os.Getpid())
        if err!=nil {return fmt.Errorf("tick %d world effect ACK: %w",count,err)}
        if accepted.WorldTargetHealthBefore!=nil {
            // Preserve raw source-native overkill across the ACK boundary;
            // the core reconciles it against gsim's clamped lethal HP.
            healthReceipt,err:=boundary.ApplyWorldTargetHealth(
                *accepted.WorldTargetHealthBefore,*accepted.WorldTargetHealthAfter,
                *accepted.WorldTargetMaxHealth,accepted.AppliedNativeDamage)
            if err!=nil {return fmt.Errorf("tick %d native world health: %w",count,err)}
            accepted.NativeWorldHealthApplied=true
            accepted.NativeRemainingHealthFraction=healthReceipt.RemainingHealthFraction
            accepted.NativeExecutePhase=healthReceipt.ExecutePhase
        }
        confirmation,err:=json.Marshal(accepted)
        if err!=nil {return err}
        if _,err:=writer.Write(append(confirmation,'\n'));err!=nil {return err}
        if err:=writer.Flush();err!=nil {return err}
        previousACKID=accepted.ACKID
        previousWorldHealthAfter=*accepted.WorldTargetHealthAfter
        previousWorldMaxHealth=*accepted.WorldTargetMaxHealth
        count++
        // The world has certified the old target's death. The same native
        // process may serve a second serial source-identical mob, but ONLY
        // after gsim selects a different living target on the next world tick.
        // EOF after this ACK remains a valid one-pull session.
        if accepted.WorldTargetHealthAfter!=nil && *accepted.WorldTargetHealthAfter==0 {
            previousWorldTargetDead=true
            previousWorldTargetID=tick.SelectedTargetID
        }
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
