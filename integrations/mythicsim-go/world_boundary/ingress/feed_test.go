package main

import (
    "math"
    "strings"
    "testing"
)

func goodTick(seq uint64, ms int64) worldTick {
    return worldTick{Type:"gsim_world_range_tick", Protocol:protocol, Sequence:seq,
        ClockMS:ms, NativeClockNS:ms*1000000, NativePlayerIndex:0,
        WorldSHA256:strings.Repeat("a",64), SelectedTargetID:"m1",
        WorldSource:"gsim.CombatRuntime", DistanceYards:20, RangeOnly:true}
}
func TestWorldRangeFeedSerialLiveTicks(t *testing.T) {
    v:=&tickValidator{}
    if err:=v.validate(goodTick(0,0));err!=nil {t.Fatal(err)}
    if err:=v.validate(goodTick(1,100));err!=nil {t.Fatal(err)}
    if v.next!=2 || v.lastClock!=100 {t.Fatal("incorrect state")}
}
func TestWorldRangeFeedRejectReplayAndBadSource(t *testing.T) {
    for _, mutate:=range []func(*worldTick){
        func(x *worldTick){x.Sequence=1},
        func(x *worldTick){x.Protocol="fake"},
        func(x *worldTick){x.NativeClockNS=1},
        func(x *worldTick){x.WorldSHA256="zz"},
        func(x *worldTick){x.DistanceYards=math.NaN()},
        func(x *worldTick){x.FacingApplied=true},
        func(x *worldTick){x.RangeOnly=false},
        func(x *worldTick){x.NativeActionACK=true},
    } {
        x:=goodTick(0,0);mutate(&x);if err:=(&tickValidator{}).validate(x);err==nil {t.Fatalf("accepted invalid %+v",x)}
    }
    v:=&tickValidator{};_ = v.validate(goodTick(0,0))
    if err:=v.validate(goodTick(1,0));err==nil {t.Fatal("accepted duplicate world time")}
}
func TestWorldRangeFeedRejectTrailingOrUnknownJSON(t *testing.T) {
    for _, raw:=range []string{
        `{"type":"gsim_world_range_tick","unexpected":4}`,
        `{} {}`,
    } {if _,err:=decodeWorldTick([]byte(raw));err==nil {t.Fatalf("accepted %s",raw)}}
}


func TestWorldTargetTransitionRequiresRealLethalACK(t *testing.T) {
    if err:=validateWorldTargetTransition("m1",false,"m1");err!=nil {t.Fatal(err)}
    if err:=validateWorldTargetTransition("m1",true,"m0");err!=nil {t.Fatal(err)}
    for _,tc:=range []struct{previous string;dead bool;next string}{
        {"m1",false,"m0"},
        {"m1",true,"m1"},
        {"",true,"m0"},
    } {
        if err:=validateWorldTargetTransition(tc.previous,tc.dead,tc.next);err==nil {
            t.Fatalf("accepted invalid serial native world retarget: %+v",tc)
        }
    }
}
