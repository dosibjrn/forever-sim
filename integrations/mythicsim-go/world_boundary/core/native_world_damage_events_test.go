package core

import (
    "math"
    "testing"
    "time"
)

// Unit fixture exercises the journal contract only. Full pinned-Go CI tests
// the SHA-pinned hook in spell_result.go and actual combat effects separately.
func TestNativeWorldDamageJournalCapturesSourceEvent(t *testing.T) {
    sim:=&Simulation{Environment:&Environment{Raid:&Raid{}},CurrentTime:75*time.Millisecond}
    session:=&WorldBoundarySession{native:sim}
    if err:=session.StartWorldDamageJournal();err!=nil {t.Fatal(err)}
    defer session.CloseWorldDamageJournal()
    player:=&Unit{Type:PlayerUnit}
    enemy:=&Unit{Type:EnemyUnit,Index:0,UnitIndex:1,Label:"native-enemy"}
    spell:=&Spell{Unit:player,ActionID:ActionID{SpellID:8921},Rank:2}
    result:=&SpellResult{Target:enemy,Damage:40,Outcome:OutcomeHit}
    recordWorldDamageForGsim(sim,spell,result,false)
    events,err:=session.DrainWorldDamageEvents()
    if err!=nil || len(events)!=1 {t.Fatalf("missing real hook fixture: %+v %v",events,err)}
    event:=events[0]
    if event.NativeTimeNS!=int64(75*time.Millisecond) || event.Damage!=40 ||
       event.EventID!="native-effect-1" || event.NativeTargetIndex!=0 ||
       event.NativeTargetUnitIndex!=1 || event.SourceActionID=="" {
        t.Fatalf("unbound source event: %+v",event)
    }
    next,err:=session.DrainWorldDamageEvents()
    if err!=nil || len(next)!=0 {t.Fatalf("replayed previously drained native event: %+v %v",next,err)}
}

func TestNativeWorldDamageJournalRejectsCorruptSource(t *testing.T) {
    sim:=&Simulation{Environment:&Environment{Raid:&Raid{}},CurrentTime:time.Second}
    session:=&WorldBoundarySession{native:sim}
    if err:=session.StartWorldDamageJournal();err!=nil {t.Fatal(err)}
    defer session.CloseWorldDamageJournal()
    recordWorldDamageForGsim(sim,&Spell{Unit:&Unit{Type:PlayerUnit}},
        &SpellResult{Target:&Unit{Type:EnemyUnit,Index:0,Label:"enemy"},Damage:math.NaN()},false)
    if _,err:=session.DrainWorldDamageEvents();err==nil {t.Fatal("accepted nonfinite native source damage")}
}

func TestNativeWorldDamageJournalDoesNotInventRegisteredSpellEvents(t *testing.T) {
    sim:=&Simulation{Environment:&Environment{Raid:&Raid{}}}
    session:=&WorldBoundarySession{native:sim}
    if err:=session.StartWorldDamageJournal();err!=nil {t.Fatal(err)}
    defer session.CloseWorldDamageJournal()
    if got,err:=session.DrainWorldDamageEvents();err!=nil || len(got)!=0 {
        t.Fatalf("reported invented native spell events: %+v %v",got,err)
    }
}


func TestNativeWorldDamageJournalCapturesPetSourceSpellResult(t *testing.T) {
    owner:=&Unit{Type:PlayerUnit,Index:0}
    sim:=&Simulation{Environment:&Environment{Raid:&Raid{AllPlayerUnits:[]*Unit{owner}}},CurrentTime:75*time.Millisecond}
    session:=&WorldBoundarySession{native:sim}
    if err:=session.StartWorldDamageJournal();err!=nil {t.Fatal(err)}
    defer session.CloseWorldDamageJournal()
    pet:=&Unit{Type:PetUnit,Index:1,UnitIndex:2,Label:"Imp"}
    enemy:=&Unit{Type:EnemyUnit,Index:0,UnitIndex:1,Label:"native-enemy"}
    spell:=&Spell{Unit:pet,ActionID:ActionID{SpellID:3110},Rank:1}
    result:=&SpellResult{Target:enemy,Damage:40,Outcome:OutcomeHit}
    recordWorldDamageForGsim(sim,spell,result,false)
    events,err:=session.DrainWorldDamageEvents()
    if err!=nil || len(events)!=1 {t.Fatalf("lost source-native pet damage: %+v %v",events,err)}
    if events[0].Damage!=40 || events[0].SourceActionID=="" ||
        events[0].NativeCasterType!="pet" || events[0].NativeCasterUnitIndex!=2 ||
        events[0].NativeCasterLabel!="Imp" {
        t.Fatalf("source pet identity/damage missing: %+v",events[0])
    }
}

func TestNativeWorldDamageJournalRejectsPetWithoutSinglePlayerOwner(t *testing.T) {
    owners:=[]*Unit{{Type:PlayerUnit,Index:0},{Type:PlayerUnit,Index:1}}
    sim:=&Simulation{Environment:&Environment{Raid:&Raid{AllPlayerUnits:owners}},CurrentTime:75*time.Millisecond}
    session:=&WorldBoundarySession{native:sim}
    if err:=session.StartWorldDamageJournal();err!=nil {t.Fatal(err)}
    defer session.CloseWorldDamageJournal()
    pet:=&Unit{Type:PetUnit,Index:1,UnitIndex:2,Label:"other-player-pet"}
    enemy:=&Unit{Type:EnemyUnit,Index:0,UnitIndex:1,Label:"native-enemy"}
    recordWorldDamageForGsim(sim,&Spell{Unit:pet,ActionID:ActionID{SpellID:3110},Rank:1},
        &SpellResult{Target:enemy,Damage:40,Outcome:OutcomeHit},false)
    if _,err:=session.DrainWorldDamageEvents();err==nil {
        t.Fatal("silently attributed an unowned pet's damage to player zero")
    }
}


func TestNativeWorldDamageJournalKeepsCommittedHPUntilWorldACK(t *testing.T) {
    sim:=&Simulation{Environment:&Environment{Raid:&Raid{},Encounter:&Encounter{}},CurrentTime:time.Second}
    sim.Encounter.DamageTaken=250
    // Outside a coupled session, upstream native damage remains authoritative.
    sim.Encounter.DamageTaken+=75
    undoUnackedWorldDamageForGsim(sim,75)
    if sim.Encounter.DamageTaken!=325 {t.Fatalf("altered ordinary native combat HP: %f",sim.Encounter.DamageTaken)}
    session:=&WorldBoundarySession{native:sim}
    if err:=session.StartWorldDamageJournal();err!=nil {t.Fatal(err)}
    // Actual spell_result.go adds raw damage, then the SHA-pinned hook
    // removes it until ApplyWorldTargetHealth receives measured gsim HP.
    sim.Encounter.DamageTaken+=75
    undoUnackedWorldDamageForGsim(sim,75)
    if sim.Encounter.DamageTaken!=325 {t.Fatalf("unACKed source damage reached native APL: %f",sim.Encounter.DamageTaken)}
    session.CloseWorldDamageJournal()
    sim.Encounter.DamageTaken+=75
    undoUnackedWorldDamageForGsim(sim,75)
    if sim.Encounter.DamageTaken!=400 {t.Fatalf("native behavior not restored after close: %f",sim.Encounter.DamageTaken)}
}
