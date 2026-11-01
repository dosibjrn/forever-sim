package core
import ("math";"strings";"testing";"time")
func TestWorldHealthACKDrivesNativeExecutePhaseWithoutDoubleDamage(t *testing.T) {
    native:=&Simulation{Environment:&Environment{Raid:&Raid{}},Duration:120*time.Second,endOfCombatDuration:120*time.Second,minTrackerTime:NeverExpires}
    session:=&WorldBoundarySession{native:native}
    result,err:=session.ApplyWorldTargetHealth(5000,4200,5000,800)
    if err!=nil {t.Fatal(err)}
    if native.endOfCombatDamage!=math.MaxFloat64 {
        t.Fatal("native scheduler would terminate on unACKed lethal raw damage")
    }
    if !session.worldHealthInitialized||native.Encounter.DamageTaken!=800||result.RemainingHealthFraction!=0.84||result.ExecutePhase>=100 {
        t.Fatalf("native did not consume world HP: %+v phase=%d damage=%f",result,native.executePhase,native.Encounter.DamageTaken)
    }
    next,err:=session.ApplyWorldTargetHealth(4200,4200,5000,0)
    if err!=nil||next.RemainingHealthFraction!=result.RemainingHealthFraction||native.Encounter.DamageTaken!=800 {
        t.Fatalf("native duplicated acknowledged damage: %+v %v",next,err)
    }
    if _,err:=session.ApplyWorldTargetHealth(4999,4000,5000,999);err==nil||!strings.Contains(err.Error(),"CONTINUITY") {
        t.Fatalf("accepted noncausal HP jump: %v",err)
    }
}

func TestWorldHealthACKAcceptsRawLethalOverkillWithoutDoubleCounting(t *testing.T) {
    native:=&Simulation{Environment:&Environment{Raid:&Raid{}},Duration:120*time.Second,
        endOfCombatDuration:120*time.Second,minTrackerTime:NeverExpires}
    session:=&WorldBoundarySession{native:native}
    if _,err:=session.ApplyWorldTargetHealth(10,10,10,0);err!=nil {t.Fatal(err)}
    if _,err:=session.ApplyWorldTargetHealth(10,0,10,9);err==nil {
        t.Fatal("accepted lethal HP loss without sufficient native source damage")
    }
    if session.worldHealthLast!=10 || native.Encounter.DamageTaken!=0 {
        t.Fatal("rejected source damage mutated native world health")
    }
    receipt,err:=session.ApplyWorldTargetHealth(10,0,10,22.5)
    if err!=nil {t.Fatalf("raw source-native overkill rejected: %v",err)}
    if session.worldHealthLast!=0 || native.Encounter.DamageTaken!=10 ||
        receipt.RemainingHealthFraction!=0 {
        t.Fatalf("lethal world ACK not applied exactly once: %+v damage=%f",receipt,native.Encounter.DamageTaken)
    }
}
