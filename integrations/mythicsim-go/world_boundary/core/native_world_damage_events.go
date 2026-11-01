// Real pinned native Go spell-effect event journal for issue #28.
//
// This file is copied into the real sim/core package. A SHA-pinned one-line
// source hook in spell_result.go calls recordWorldDamageForGsim at the actual
// native DealDamage boundary. This does NOT invent an action from DPS counters.
package core

import (
    "errors"
    "fmt"
    "math"
    "sync"
    "time"
)

// WorldNativeDamageEvent is an observed native spell RESULT, before world ACK.
// Application to the real gsim world is handled by the Python controller.
type WorldNativeDamageEvent struct {
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
    // Empty for the original player-only protocol; nonempty for native pets.
    NativeCasterType string `json:"native_caster_type,omitempty"`
    NativeCasterUnitIndex int32 `json:"native_caster_unit_index,omitempty"`
    NativeCasterLabel string `json:"native_caster_label,omitempty"`
}

type nativeWorldDamageJournal struct {
    mu sync.Mutex
    events []WorldNativeDamageEvent
    next uint64
    lastTime time.Duration
    err error
}

var nativeWorldDamageJournals sync.Map // map[*Simulation]*nativeWorldDamageJournal

func (session *WorldBoundarySession) StartWorldDamageJournal() error {
    if session == nil || session.native == nil || session.native.Raid == nil {
        return errors.New("WORLD_DAMAGE_JOURNAL_NATIVE_SESSION_MISSING")
    }
    state := &nativeWorldDamageJournal{}
    if _, already := nativeWorldDamageJournals.LoadOrStore(session.native,state); already {
        return errors.New("WORLD_DAMAGE_JOURNAL_DUPLICATE_SESSION")
    }
    return nil
}

func (session *WorldBoundarySession) CloseWorldDamageJournal() {
    if session != nil && session.native != nil {
        nativeWorldDamageJournals.Delete(session.native)
    }
}

// Invoked only at the *real* pinned spell.dealDamageInternal source location;
// never from Python, a fake action registry or a synthetic DPS trace.
func recordWorldDamageForGsim(sim *Simulation, spell *Spell, result *SpellResult, periodic bool) {
    raw, ok := nativeWorldDamageJournals.Load(sim)
    if !ok { return }
    state := raw.(*nativeWorldDamageJournal)
    state.mu.Lock()
    defer state.mu.Unlock()
    if state.err != nil { return }
    if spell == nil || result == nil || result.Target == nil || spell.Unit == nil {
        state.err=errors.New("NATIVE_WORLD_DAMAGE_MALFORMED_SPELL_RESULT")
        return
    }
    // Only the selected enemy is coupled to gsim. Pets of the single native
    // player are real damage sources: dropping their spell results would make
    // the gsim target survive hits that the native engine actually dealt.
    if result.Target.Type != EnemyUnit || result.Damage == 0 || sim.CurrentTime < 0 { return }
    if spell.Unit.Type != PlayerUnit && spell.Unit.Type != PetUnit {
        state.err=errors.New("NATIVE_WORLD_DAMAGE_CASTER_UNSUPPORTED")
        return
    }
    // A pet's Index is a raid-wide PET ordinal (not its owner's player
    // index). In this one-player world coupling, a real source pet belongs
    // to the sole player; never assume pet.Index == player.Index.
    if (spell.Unit.Type==PlayerUnit && spell.Unit.Index!=0) ||
        (spell.Unit.Type==PetUnit &&
            (len(sim.Raid.AllPlayerUnits)!=1 || sim.Raid.AllPlayerUnits[0]==nil)) {
        state.err=errors.New("NATIVE_WORLD_DAMAGE_CASTER_NOT_SINGLE_PLAYER")
        return
    }
    casterType:=""
    casterIndex:=int32(0)
    casterLabel:=""
    if spell.Unit.Type==PetUnit {
        if spell.Unit.UnitIndex<0 || spell.Unit.Label=="" {
            state.err=errors.New("NATIVE_WORLD_DAMAGE_PET_IDENTITY_MISSING")
            return
        }
        casterType="pet"
        casterIndex=spell.Unit.UnitIndex
        casterLabel=spell.Unit.Label
    }
    if math.IsNaN(result.Damage) || math.IsInf(result.Damage,0) || result.Damage < 0 {
        state.err=errors.New("NATIVE_WORLD_DAMAGE_INVALID")
        return
    }
    target := result.Target
    if target.Index != 0 || target.Label == "" {
        state.err=errors.New("NATIVE_WORLD_DAMAGE_TARGET_NOT_SINGLE_ENEMY")
        return
    }
    if sim.CurrentTime < state.lastTime {
        state.err=errors.New("NATIVE_WORLD_DAMAGE_TIMESTAMP_ROLLBACK")
        return
    }
    state.next++
    state.events=append(state.events,WorldNativeDamageEvent{
        EventID:fmt.Sprintf("native-effect-%d",state.next),
        NativeTimeNS:int64(sim.CurrentTime),SourceActionID:spell.ActionID.String(),
        Rank:spell.Rank,NativeTargetIndex:target.Index,
        NativeTargetUnitIndex:target.UnitIndex,NativeTargetLabel:target.Label,
        Damage:result.Damage,Landed:result.Landed(),Crit:result.DidCrit(),Periodic:periodic,
        NativeCasterType:casterType,NativeCasterUnitIndex:casterIndex,NativeCasterLabel:casterLabel,
    })
    state.lastTime=sim.CurrentTime
}

// Drain only AFTER the associated world range was applied and native events
// before the next world tick were executed. The caller MUST obtain a real
// gsim applied-world ACK before it advances the native scheduler again.
func (session *WorldBoundarySession) DrainWorldDamageEvents() ([]WorldNativeDamageEvent,error) {
    if session == nil || session.native == nil {
        return nil,errors.New("WORLD_DAMAGE_JOURNAL_NO_SESSION")
    }
    if session.awaitingWorld {
        return nil,errors.New("WORLD_DAMAGE_JOURNAL_RANGE_ACK_PENDING")
    }
    raw,ok:=nativeWorldDamageJournals.Load(session.native)
    if !ok { return nil,errors.New("WORLD_DAMAGE_JOURNAL_NOT_ENABLED") }
    state:=raw.(*nativeWorldDamageJournal)
    state.mu.Lock()
    defer state.mu.Unlock()
    if state.err!=nil { return nil,state.err }
    result:=append([]WorldNativeDamageEvent{},state.events...)
    state.events=state.events[:0]
    return result,nil
}
