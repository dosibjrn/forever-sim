package core

import (
    "math"
    "strings"
    "testing"
)

// Source-data unit regression only; the complete pinned native runtime probe
// is separately required before claiming actual combat execution.
func testWorldNativeMetricsSession(spell *Spell) *WorldBoundarySession {
    player := &Unit{Spellbook: []*Spell{spell}}
    native := &Simulation{Environment: &Environment{
        Raid: &Raid{AllPlayerUnits: []*Unit{player}},
    }}
    return &WorldBoundarySession{native: native}
}

func TestNativeSpellCountersRetainInactiveSplits(t *testing.T) {
    spell := &Spell{ActionID: ActionID{SpellID: 8921}, Rank: 2}
    spell.splitSpellMetrics = [][]SpellMetrics{
        {{Casts: 2, Hits: 1, TotalDamage: 100}},
        {{Casts: 1, Hits: 1, TotalDamage: 50}},
    }
    spell.SpellMetrics = spell.splitSpellMetrics[1]
    session := testWorldNativeMetricsSession(spell)
    rows, err := session.NativeSpellCounters(0)
    if err != nil { t.Fatal(err) }
    if len(rows) != 1 || rows[0].Casts != 3 || rows[0].Hits != 2 || rows[0].TotalDamage != 150 {
        t.Fatalf("must preserve counters across old and active splits: %+v", rows)
    }
    // A split switch cannot erase already-paid native results.
    spell.SpellMetrics = spell.splitSpellMetrics[0]
    after, err := session.NativeSpellCounters(0)
    if err != nil || after[0].Casts != 3 || after[0].TotalDamage != 150 {
        t.Fatalf("switch reset counters: %+v, %v", after, err)
    }
}

func TestNativeSpellCountersRejectUnavailableAndInvalid(t *testing.T) {
    if _,err := (&WorldBoundarySession{}).NativeSpellCounters(0);err==nil {
        t.Fatal("nil native accepted")
    }
    spell := &Spell{ActionID: ActionID{SpellID: 8921},
        SpellMetrics: []SpellMetrics{{Casts: 1, TotalDamage: 10}}}
    session := testWorldNativeMetricsSession(spell)
    session.awaitingWorld = true
    if _,err := session.NativeSpellCounters(0);err == nil ||
        !strings.Contains(err.Error(),"WORLD_TICK_NOT_APPLIED") {
        t.Fatalf("observed metrics before ACK: %v", err)
    }
    session.awaitingWorld = false
    if _,err := session.NativeSpellCounters(1);err==nil {
        t.Fatal("bad native player index accepted")
    }
    spell.SpellMetrics[0].TotalDamage=math.NaN()
    if _,err := session.NativeSpellCounters(0);err==nil {
        t.Fatal("nonfinite native metrics accepted")
    }
}

func TestNativeSpellCountersSkipUnexecutedRegisteredSpells(t *testing.T) {
    session := testWorldNativeMetricsSession(&Spell{
        ActionID:ActionID{SpellID:8921},
        SpellMetrics:[]SpellMetrics{{}},
    })
    rows,err := session.NativeSpellCounters(0)
    if err!=nil || len(rows)!=0 {
        t.Fatalf("registered-but-unexecuted spell incorrectly reported: %+v %v", rows,err)
    }
}
