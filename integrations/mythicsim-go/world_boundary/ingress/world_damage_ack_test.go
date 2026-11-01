package main

import (
    "encoding/json"
    "strings"
    "testing"
)

func ackFixture(tick worldTick, events []sourceNativeEventProof, pid int) []byte {
    ids:=make([]string,0,len(events))
    damage:=0.0
    for _,e:=range events {
        ids=append(ids,e.EventID)
        damage+=e.Damage
    }
    after:=tick.WorldSHA256
    if damage>0 {after=strings.Repeat("b",64)}
    hpBefore,hpMax:=1000.0,1000.0
    hpAfter:=hpBefore-damage
    if hpAfter<0 {hpAfter=0}
    raw,_:=json.Marshal(worldDamageAck{
        Type:"gsim_native_damage_applied_ack",Sequence:tick.Sequence,
        NativeProcessID:pid,WorldBeforeSHA256:tick.WorldSHA256,
        WorldAfterSHA256:after,AppliedEventIDs:ids,AppliedEvents:events,AppliedNativeDamage:damage,
        WorldTargetHealthBefore:&hpBefore,WorldTargetHealthAfter:&hpAfter,WorldTargetMaxHealth:&hpMax,
    })
    return raw
}

func nativeRealEventProof() sourceNativeEventProof {
    return sourceNativeEventProof{
        EventID:"native-effect-1",NativeTimeNS:75000000,
        SourceActionID:"SpellID:8921",Rank:2,
        NativeTargetIndex:0,NativeTargetUnitIndex:1,NativeTargetLabel:"native-mob",
        Damage:22.5,Landed:true,Crit:false,Periodic:false,
    }
}

func TestRealWorldEffectACKAcceptsExactNativeEventProof(t *testing.T) {
    tick:=goodTick(0,100)
    events:=[]sourceNativeEventProof{nativeRealEventProof()}
    accepted,err:=checkWorldEffectACK(ackFixture(tick,events,123),tick,events,123)
    if err!=nil {t.Fatal(err)}
    if accepted.ACKID=="" || !accepted.NativeSpellActionACK || accepted.CheckpointCertified {
        t.Fatalf("missing genuine acknowledgement scope: %+v",accepted)
    }
}

func TestRealWorldEffectACKRejectsAbsentOrReplayedSourceEvents(t *testing.T) {
    tick:=goodTick(0,100)
    events:=[]sourceNativeEventProof{nativeRealEventProof()}
    raw:=ackFixture(tick,events,123)
    for name,mutate:=range map[string]func(*worldDamageAck){
        "wrong-event":func(a *worldDamageAck){a.AppliedEventIDs[0]="native-effect-2"},
        "wrong-damage":func(a *worldDamageAck){a.AppliedNativeDamage=0},
        "wrong-seq":func(a *worldDamageAck){a.Sequence=1},
        "wrong-pid":func(a *worldDamageAck){a.NativeProcessID=42},
        "unchanged-world":func(a *worldDamageAck){a.WorldAfterSHA256=a.WorldBeforeSHA256},
        "wrong-clock":func(a *worldDamageAck){a.AppliedEvents[0].NativeTimeNS++},
        "wrong-spell":func(a *worldDamageAck){a.AppliedEvents[0].SourceActionID="other-spell"},
        "wrong-rank":func(a *worldDamageAck){a.AppliedEvents[0].Rank++},
        "wrong-target":func(a *worldDamageAck){a.AppliedEvents[0].NativeTargetUnitIndex++},
        "wrong-target-label":func(a *worldDamageAck){a.AppliedEvents[0].NativeTargetLabel="different-mob"},
        "wrong-outcome":func(a *worldDamageAck){a.AppliedEvents[0].Crit=true},
    } {
        var a worldDamageAck
        _=json.Unmarshal(raw,&a)
        mutate(&a)
        changed,_:=json.Marshal(a)
        if _,err:=checkWorldEffectACK(changed,tick,events,123);err==nil {
            t.Fatalf("accepted %s",name)
        }
    }
    future:=[]sourceNativeEventProof{nativeRealEventProof()}
    future[0].NativeTimeNS=200000000
    if _,err:=checkWorldEffectACK(raw,tick,future,123);err==nil {t.Fatal("future event accepted")}
}

func TestRealWorldEffectACKEmptyTickRequiresUnchangedWorld(t *testing.T) {
    tick:=goodTick(0,100)
    result,err:=checkWorldEffectACK(ackFixture(tick,nil,77),tick,nil,77)
    if err!=nil || result.NativeSpellActionACK {t.Fatalf("false positive ACK: %+v %v",result,err)}
}

func TestRealWorldEffectACKRejectsTrailingData(t *testing.T) {
    tick:=goodTick(0,100)
    raw:=append(ackFixture(tick,nil,77),[]byte(` {"type":"spoof"}`)...)
    if _,err:=checkWorldEffectACK(raw,tick,nil,77);err==nil {t.Fatal("accepted extra JSON")}
}

func TestNativeWorldACKHashBindsFullSourceSpellAndTarget(t *testing.T) {
    tick:=goodTick(0,100)
    original:=nativeRealEventProof()
    baseline:=[]sourceNativeEventProof{original}
    accepted,err:=checkWorldEffectACK(ackFixture(tick,baseline,123),tick,baseline,123)
    if err!=nil {t.Fatal(err)}
    variants:=[]sourceNativeEventProof{original,original,original,original}
    variants[0].SourceActionID="SpellID:774"
    variants[1].NativeTargetLabel="other-native-mob"
    variants[2].Damage=24.0
    variants[3].Periodic=true
    for _,event:=range variants {
        source:=[]sourceNativeEventProof{event}
        result,err:=checkWorldEffectACK(ackFixture(tick,source,123),tick,source,123)
        if err!=nil {t.Fatal(err)}
        if result.ACKID==accepted.ACKID {
            t.Fatalf("ACK hash omitted native spell/target/damage/outcome: %+v",event)
        }
    }
}

func TestWorldEffectACKHealthDeltaBoundToRealNativeDamage(t *testing.T) {
    tick:=goodTick(0,100)
    events:=[]sourceNativeEventProof{nativeRealEventProof()}
    var ack worldDamageAck
    if err:=json.Unmarshal(ackFixture(tick,events,123),&ack);err!=nil {t.Fatal(err)}
    before,after,maxHP:=700.0,677.5,700.0
    ack.WorldTargetHealthBefore=&before
    ack.WorldTargetHealthAfter=&after
    ack.WorldTargetMaxHealth=&maxHP
    raw,_:=json.Marshal(ack)
    result,err:=checkWorldEffectACK(raw,tick,events,123)
    if err!=nil || result.WorldTargetHealthAfter==nil || *result.WorldTargetHealthAfter!=after {
        t.Fatalf("real source HP ACK rejected: %+v %v",result,err)
    }
    after=675
    raw,_=json.Marshal(ack)
    if _,err:=checkWorldEffectACK(raw,tick,events,123);err==nil {
        t.Fatal("accepted health change not backed by native spell event")
    }
}

func TestWorldEffectACKAcceptsLethalSourceOverkillAndRejectsInventedHP(t *testing.T) {
    tick:=goodTick(0,100)
    events:=[]sourceNativeEventProof{nativeRealEventProof()} // raw 22.5 damage
    var ack worldDamageAck
    if err:=json.Unmarshal(ackFixture(tick,events,123),&ack);err!=nil {t.Fatal(err)}
    before,after,maxHP:=10.0,0.0,10.0
    ack.WorldTargetHealthBefore=&before
    ack.WorldTargetHealthAfter=&after
    ack.WorldTargetMaxHealth=&maxHP
    raw,_:=json.Marshal(ack)
    result,err:=checkWorldEffectACK(raw,tick,events,123)
    if err!=nil || result.WorldTargetHealthAfter==nil || *result.WorldTargetHealthAfter!=0 {
        t.Fatalf("rejected real lethal overkill: %+v %v",result,err)
    }
    // Raw native damage exceeded the world target's remaining HP. Any
    // surviving HP or inflated HP loss is inconsistent with that event.
    after=1
    raw,_=json.Marshal(ack)
    if _,err:=checkWorldEffectACK(raw,tick,events,123);err==nil {
        t.Fatal("accepted world target surviving a lethal source event")
    }
}

func TestWorldEffectACKCannotSkipNativeHealthFeedback(t *testing.T) {
    tick:=goodTick(0,100)
    for _,events:=range [][]sourceNativeEventProof{
        nil, {nativeRealEventProof()},
    } {
        var ack worldDamageAck
        if err:=json.Unmarshal(ackFixture(tick,events,123),&ack);err!=nil {t.Fatal(err)}
        // A world hash and exact spell transcript alone do not prove that
        // the next native decision consumed the actual gsim target health.
        ack.WorldTargetHealthBefore=nil
        ack.WorldTargetHealthAfter=nil
        ack.WorldTargetMaxHealth=nil
        raw,_:=json.Marshal(ack)
        if _,err:=checkWorldEffectACK(raw,tick,events,123);err==nil ||
            !strings.Contains(err.Error(),"WORLD_EFFECT_ACK_HEALTH_FIELDS_INCOMPLETE") {
            t.Fatalf("accepted ACK without native health feedback (events=%d): %v",len(events),err)
        }
    }
}


func TestWorldEffectACKBindsRealPetCasterAndRejectsForgedCaster(t *testing.T) {
    tick:=goodTick(0,100)
    pet:=nativeRealEventProof()
    pet.NativeCasterType="pet"
    pet.NativeCasterUnitIndex=2
    pet.NativeCasterLabel="Imp"
    events:=[]sourceNativeEventProof{pet}
    accepted,err:=checkWorldEffectACK(ackFixture(tick,events,123),tick,events,123)
    if err!=nil || !accepted.NativeSpellActionACK {t.Fatalf("source pet ACK missing: %+v %v",accepted,err)}
    var forged worldDamageAck
    if err:=json.Unmarshal(ackFixture(tick,events,123),&forged);err!=nil {t.Fatal(err)}
    forged.AppliedEvents[0].NativeCasterLabel="other-pet"
    raw,_:=json.Marshal(forged)
    if _,err:=checkWorldEffectACK(raw,tick,events,123);err==nil {t.Fatal("accepted forged pet caster identity")}
    malformed:=pet
    malformed.NativeCasterLabel=""
    if _,err:=checkWorldEffectACK(ackFixture(tick,[]sourceNativeEventProof{malformed},123),
        tick,[]sourceNativeEventProof{malformed},123);err==nil {t.Fatal("accepted pet with missing source label")}
}
