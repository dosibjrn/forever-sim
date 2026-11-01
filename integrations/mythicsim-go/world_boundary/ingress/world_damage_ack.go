// Explicit gsim-applied native-effect ACK: source Go event IDs, native clock,
// process ID and actual changed gsim world snapshot must all match.
// ACK is REQUIRED for each range tick, even when no native effect fired.
package main

import (
    "bytes"
    "crypto/sha256"
    "encoding/hex"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "math"
    "os"

)

type worldDamageAck struct {
    Type string `json:"type"`
    Sequence uint64 `json:"sequence"`
    NativeProcessID int `json:"native_process_id"`
    WorldBeforeSHA256 string `json:"world_before_sha256"`
    WorldAfterSHA256 string `json:"world_after_sha256"`
    AppliedEventIDs []string `json:"applied_event_ids"`
    AppliedEvents []sourceNativeEventProof `json:"applied_events"`
    AppliedNativeDamage float64 `json:"applied_native_damage"`
    WorldTargetHealthBefore *float64 `json:"world_target_health_before,omitempty"`
    WorldTargetHealthAfter *float64 `json:"world_target_health_after,omitempty"`
    WorldTargetMaxHealth *float64 `json:"world_target_max_health,omitempty"`
}

type worldAckAccepted struct {
    Type string `json:"type"`
    Sequence uint64 `json:"sequence"`
    ACKID string `json:"ack_id"`
    ObservedWorldAfterSHA256 string `json:"observed_world_after_sha256"`
    NativeProcessID int `json:"native_process_id"`
    NativeSpellActionACK bool `json:"native_spell_action_ack"`
    CheckpointCertified bool `json:"checkpoint_certified"`
    NativeWorldHealthApplied bool `json:"native_world_health_applied"`
    NativeRemainingHealthFraction float64 `json:"native_remaining_health_fraction"`
    NativeExecutePhase int32 `json:"native_execute_phase"`
    WorldTargetHealthBefore *float64 `json:"-"`
    WorldTargetHealthAfter *float64 `json:"-"`
    WorldTargetMaxHealth *float64 `json:"-"`
}

func validHash(value string) bool {
    b,err:=hex.DecodeString(value)
    return err==nil && len(value)==64 && len(b)==32
}

type sourceNativeEventProof struct {
    EventID string `json:"event_id"`
    NativeTimeNS int64 `json:"native_time_ns"`
    SourceActionID string `json:"source_action_id"`
    Rank int32 `json:"rank"`
    NativeTargetIndex int32 `json:"native_target_index"`
    NativeTargetUnitIndex int32 `json:"native_target_unit_index"`
    NativeTargetLabel string `json:"native_target_label"`
    Damage float64 `json:"damage"`
    Landed bool `json:"landed"`
    Crit bool `json:"crit"`
    Periodic bool `json:"periodic"`
}

func checkWorldEffectACK(raw []byte, tick worldTick, events []sourceNativeEventProof, pid int) (worldAckAccepted,error) {
    var ack worldDamageAck
    if err:=decodeStrictJSON(raw,&ack);err!=nil {return worldAckAccepted{},err}
    if ack.Type!="gsim_native_damage_applied_ack" || ack.Sequence!=tick.Sequence ||
        ack.NativeProcessID!=pid || ack.WorldBeforeSHA256!=tick.WorldSHA256 ||
        !validHash(ack.WorldAfterSHA256) {
        return worldAckAccepted{},errors.New("WORLD_EFFECT_ACK_ID_OR_HASH_MISMATCH")
    }
    if len(ack.AppliedEventIDs)!=len(events) || len(ack.AppliedEvents)!=len(events) {
        return worldAckAccepted{},errors.New("WORLD_EFFECT_ACK_EVENT_COUNT_MISMATCH")
    }
    applied:=0.0
    for index,event:=range events {
        // ACK must echo the entire source-native event, not just a forgeable
        // event ID/damage pair. Time, spell rank, target and flags are checked.
        claim:=ack.AppliedEvents[index]
        if claim!=event || event.EventID=="" ||
            event.EventID!=ack.AppliedEventIDs[index] ||
            event.NativeTimeNS<0 || event.NativeTimeNS>tick.NativeClockNS ||
            event.SourceActionID=="" || event.Rank<0 ||
            event.NativeTargetIndex!=0 || event.NativeTargetUnitIndex<0 ||
            event.NativeTargetLabel=="" || !event.Landed ||
            math.IsNaN(event.Damage) || math.IsInf(event.Damage,0) || event.Damage<=0 {
            return worldAckAccepted{},fmt.Errorf("WORLD_EFFECT_ACK_EVENT_MISMATCH:%d",index)
        }
        applied+=event.Damage
    }
    if math.IsNaN(applied) || math.IsInf(applied,0) ||
        math.IsNaN(ack.AppliedNativeDamage) || math.IsInf(ack.AppliedNativeDamage,0) ||
        math.Abs(applied-ack.AppliedNativeDamage)>1e-6 {
        return worldAckAccepted{},errors.New("WORLD_EFFECT_ACK_DAMAGE_MISMATCH")
    }
    healthPresent:=ack.WorldTargetHealthBefore!=nil || ack.WorldTargetHealthAfter!=nil || ack.WorldTargetMaxHealth!=nil
    if healthPresent {
        if ack.WorldTargetHealthBefore==nil || ack.WorldTargetHealthAfter==nil || ack.WorldTargetMaxHealth==nil {
            return worldAckAccepted{},errors.New("WORLD_EFFECT_ACK_HEALTH_FIELDS_INCOMPLETE")
        }
        before,after,maxHP:=*ack.WorldTargetHealthBefore,*ack.WorldTargetHealthAfter,*ack.WorldTargetMaxHealth
        if math.IsNaN(before) || math.IsNaN(after) || math.IsNaN(maxHP) ||
            math.IsInf(before,0) || math.IsInf(after,0) || math.IsInf(maxHP,0) ||
            maxHP<=0 || before<0 || after<0 || before>maxHP || after>before ||
            // Native damage is raw source damage. Gsim clamps a lethal hit
            // to zero HP; the world delta is min(raw damage, remaining HP).
            math.Abs(before-after-math.Min(applied,before))>1e-6 {
            return worldAckAccepted{},errors.New("WORLD_EFFECT_ACK_HEALTH_DELTA_MISMATCH")
        }
    }
    if (applied>0 && ack.WorldAfterSHA256==tick.WorldSHA256) ||
        (applied==0 && ack.WorldAfterSHA256!=tick.WorldSHA256) {
        return worldAckAccepted{},errors.New("WORLD_EFFECT_ACK_WORLD_NOT_APPLIED")
    }
    // Bind next-tick ACK to the ENTIRE verified native effect transcript.
    // Event ID alone is insufficient: identical IDs with different source
    // spell/target/outcome must never yield the same causal ACK identity.
    eventBytes,err:=json.Marshal(events)
    if err!=nil {return worldAckAccepted{},err}
    digestInput:=append([]byte(fmt.Sprintf(
        "gsim-native-ACK-v2:%d:%d:%s:%s:",pid,tick.Sequence,
        ack.WorldBeforeSHA256,ack.WorldAfterSHA256)),eventBytes...)
    if healthPresent {
        digestInput=append(digestInput,[]byte(fmt.Sprintf(":world-hp:%.17g:%.17g:%.17g",
            *ack.WorldTargetHealthBefore,*ack.WorldTargetHealthAfter,*ack.WorldTargetMaxHealth))...)
    }
    digest:=sha256.Sum256(digestInput)
    return worldAckAccepted{Type:"native_go_world_ack_accepted",
        Sequence:tick.Sequence,ACKID:hex.EncodeToString(digest[:]),
        ObservedWorldAfterSHA256:ack.WorldAfterSHA256,
        NativeProcessID:os.Getpid(),
        NativeSpellActionACK:len(events)>0,CheckpointCertified:false,
        WorldTargetHealthBefore:ack.WorldTargetHealthBefore,
        WorldTargetHealthAfter:ack.WorldTargetHealthAfter,
        WorldTargetMaxHealth:ack.WorldTargetMaxHealth},nil
}

func decodeStrictJSON(data []byte, out any) error {
    // JSONL messages are deliberately one object. Strict decoding rejects
    // invented unknown ACK fields and multiple appended JSON objects.
    decoder:=json.NewDecoder(bytes.NewReader(data))
    decoder.DisallowUnknownFields()
    if err:=decoder.Decode(out);err!=nil {return err}
    var next any
    if err:=decoder.Decode(&next);err!=io.EOF {
        return errors.New("WORLD_EFFECT_ACK_TRAILING_JSON")
    }
    return nil
}
