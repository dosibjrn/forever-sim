package core

import (
	"strings"
	"testing"
	"time"
)

func TestNextWorldNativeEventIncludesAllQueues(t *testing.T) {
	sim := &Simulation{
		pendingActions:      []*PendingAction{sentinelPendingAction, {NextActionAt: 20 * time.Millisecond}},
		minWeaponAttackTime: 10 * time.Millisecond,
		minTaskTime:         15 * time.Millisecond,
	}
	if got := sim.nextWorldNativeEventAt(); got != 10*time.Millisecond {
		t.Fatalf("want weapon 10ms, got %s", got)
	}
	sim.minWeaponAttackTime = NeverExpires
	if got := sim.nextWorldNativeEventAt(); got != 15*time.Millisecond {
		t.Fatalf("want task 15ms, got %s", got)
	}
	sim.minTaskTime = NeverExpires
	if got := sim.nextWorldNativeEventAt(); got != 20*time.Millisecond {
		t.Fatalf("want pending 20ms, got %s", got)
	}
}

func TestWorldSessionRequiresRealNativeAndACKOrder(t *testing.T) {
	if _, err := NewWorldBoundarySession(nil); err == nil {
		t.Fatal("nil native accepted")
	}
	session := &WorldBoundarySession{}
	if _, err := session.ApplyWorldDistance(0, 0, 10); err == nil || !strings.Contains(err.Error(), "WITHOUT_PENDING_TICK") {
		t.Fatalf("unexpected %v", err)
	}
	if _, err := session.AdvanceToWorldTick(time.Second, 1); err == nil {
		t.Fatal("nil native advanced")
	}
}

func TestWorldBoundaryRequiresAppliedTickBeforeNextNativeEvent(t *testing.T) {
	// This only checks fail-closed sequencing, not native combat execution.
	native := &Simulation{Environment: &Environment{Raid: &Raid{}}, endOfCombatDuration: time.Second}
	session, err := NewWorldBoundarySession(native)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := session.AdvanceToWorldTick(0, 1); err != nil {
		t.Fatal(err)
	}
	if _, err := session.AdvanceToWorldTick(time.Millisecond, 1); err == nil || !strings.Contains(err.Error(), "PREVIOUS_WORLD_TICK_NOT_APPLIED") {
		t.Fatalf("advanced without world: %v", err)
	}
	if _, err := session.ApplyWorldDistance(1, 0, 10); err == nil || !strings.Contains(err.Error(), "WORLD_SEQUENCE_MISMATCH") {
		t.Fatalf("accepted forged sequence: %v", err)
	}
}
