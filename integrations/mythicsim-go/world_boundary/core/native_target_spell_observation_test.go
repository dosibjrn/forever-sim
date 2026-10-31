package core

import (
    "strings"
    "testing"
)

func sourceTargetSession(spell *Spell) *WorldBoundarySession {
    enemy:=&Unit{Type:EnemyUnit,Index:0,UnitIndex:1,Label:"native-encounter-target-0"}
    player:=&Unit{Type:PlayerUnit,Index:0,UnitIndex:0,Spellbook:[]*Spell{spell}}
    return &WorldBoundarySession{native:&Simulation{Environment:&Environment{
        Raid:&Raid{AllPlayerUnits:[]*Unit{player}},
        Encounter:Encounter{ActiveTargetUnits:[]*Unit{enemy}},
    }}}
}

func TestNativeTargetSpellsOnlyMeasureActualEnemy(t *testing.T) {
    spell:=&Spell{ActionID:ActionID{SpellID:8921},Rank:2,
        SpellMetrics:[]SpellMetrics{
            {Casts:99,TotalDamage:9999}, // friendly/player target MUST NOT count
            {Casts:1,Hits:1,TotalDamage:125},
        },
    }
    rows,err:=sourceTargetSession(spell).NativeSingleTargetSpellCounters(0)
    if err!=nil {t.Fatal(err)}
    if len(rows)!=1 || rows[0].TotalDamage!=125 || rows[0].Casts!=1 ||
        rows[0].NativeTargetIndex!=0 || rows[0].NativeTargetUnitIndex!=1 {
        t.Fatalf("target metrics incorrectly aggregated: %+v",rows)
    }
}

func TestNativeTargetSpellsRejectPreACKRead(t *testing.T) {
    session:=sourceTargetSession(&Spell{ActionID:ActionID{SpellID:8921},
        SpellMetrics:[]SpellMetrics{{}, {Casts:1,TotalDamage:25}}})
    session.awaitingWorld=true
    if _,err:=session.NativeSingleTargetSpellCounters(0);err==nil ||
        !strings.Contains(err.Error(),"ACK_PENDING") {
        t.Fatalf("read before world range apply: %v",err)
    }
}

func TestNativeTargetSpellsNoMetricProvenanceNoActivity(t *testing.T) {
    session:=sourceTargetSession(&Spell{ActionID:ActionID{SpellID:8921},
        SpellMetrics:[]SpellMetrics{{}, {}}})
    rows,err:=session.NativeSingleTargetSpellCounters(0)
    if err!=nil || len(rows)!=0 {t.Fatalf("fabricated source activity: %+v %v",rows,err)}
}
