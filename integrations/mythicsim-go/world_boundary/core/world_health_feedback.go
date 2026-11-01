package core
import ("errors";"math")
type WorldTargetHealthReceipt struct {
    RemainingHealthFraction float64 `json:"remaining_health_fraction"`
    ExecutePhase int32 `json:"execute_phase"`
}
// Only call after the source-event/world ACK is verified. The real native
// combat scheduler and APL read this reconciled world HP at their next step.
func (session *WorldBoundarySession) ApplyWorldTargetHealth(before,after,maxHP,nativeDamage float64) (WorldTargetHealthReceipt,error) {
    if session==nil || session.native==nil || session.awaitingWorld {return WorldTargetHealthReceipt{},errors.New("NATIVE_WORLD_HEALTH_SESSION_NOT_READY")}
    sim:=session.native
    if math.IsNaN(before)||math.IsNaN(after)||math.IsNaN(maxHP)||math.IsNaN(nativeDamage)||
        math.IsInf(before,0)||math.IsInf(after,0)||math.IsInf(maxHP,0)||math.IsInf(nativeDamage,0)||
        maxHP<=0||before<0||after<0||before>maxHP||after>before||nativeDamage<0||
        math.Abs(before-after-nativeDamage)>1e-6 {return WorldTargetHealthReceipt{},errors.New("NATIVE_WORLD_HEALTH_INVALID")}
    if session.worldHealthInitialized {
        if math.Abs(maxHP-session.worldHealthMax)>1e-6||math.Abs(before-session.worldHealthLast)>1e-6 {
            return WorldTargetHealthReceipt{},errors.New("NATIVE_WORLD_HEALTH_CONTINUITY_MISMATCH")
        }
    } else {
        // Keep the request's time cap, but use actual world HP for execute
        // phase and remaining-health decisions in this hybrid session.
        sim.Encounter.EndFightAtHealth=maxHP
        // The gsim world, not native pre-ACK raw spell damage, owns death.
        // Keep health-based execute/APL decisions but never let Step() stop
        // the native scheduler before a lethal source event reaches gsim.
        sim.endOfCombatDamage=math.MaxFloat64
        sim.executePhase=0
        sim.nextExecutePhase()
        session.worldHealthMax=maxHP
        session.worldHealthInitialized=true
    }
    // Native spell damage is already counted; never add it twice.
    sim.Encounter.DamageTaken=maxHP-after
    session.worldHealthLast=after
    sim.advance(sim.CurrentTime)
    return WorldTargetHealthReceipt{RemainingHealthFraction:sim.GetRemainingDurationPercent(),ExecutePhase:sim.executePhase},nil
}
func (session *WorldBoundarySession) WorldHealthDecisionSnapshot() (float64,int32,bool) {
    if session==nil||session.native==nil||!session.worldHealthInitialized {return 0,0,false}
    return session.native.GetRemainingDurationPercent(),session.native.executePhase,true
}


// BeginNextWorldTarget retains the *same* native Simulation, actor, cooldowns,
// resources, RNG, and event journal after a real lethal gsim world ACK.
// This serial one-native-target-slot contract is valid only for successive
// identical source enemy templates; the gsim controller owns target identity.
// Native target auras are encounter-scoped and must not leak to the next mob.
func (session *WorldBoundarySession) BeginNextWorldTarget() error {
    if session==nil || session.native==nil || session.awaitingWorld ||
        !session.worldHealthInitialized || session.worldHealthLast!=0 {
        return errors.New("NATIVE_WORLD_NEXT_TARGET_REQUIRES_LETHAL_ACK")
    }
    sim:=session.native
    if len(sim.Encounter.AllTargets)!=1 ||
        sim.Raid==nil || len(sim.Raid.AllPlayerUnits)!=1 ||
        sim.Raid.AllPlayerUnits[0]==nil || sim.Raid.AllPlayerUnits[0].Moving {
        return errors.New("NATIVE_WORLD_NEXT_TARGET_REQUIRES_SINGLE_NATIVE_SLOT")
    }
    target:=sim.Encounter.AllTargets[0]
    if target==nil {return errors.New("NATIVE_WORLD_NEXT_TARGET_MISSING")}
    // A native DOT/control aura belongs to the dead mob, never the new one.
    target.auraTracker.expireAll(sim)
    // Park the real player out of combat range while native time, regen and
    // cooldowns advance through gsim's recovery interval.
    applyWorldDistanceToPlayer(sim,sim.Raid.AllPlayerUnits[0],10000)
    sim.Encounter.DamageTaken=0
    sim.executePhase=0
    sim.nextExecutePhase()
    session.worldHealthInitialized=false
    session.worldHealthMax=0
    session.worldHealthLast=0
    return nil
}
