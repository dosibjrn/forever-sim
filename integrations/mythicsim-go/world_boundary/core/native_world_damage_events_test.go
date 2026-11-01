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
