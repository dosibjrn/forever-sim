// This file is an additive source overlay copied into the exact pinned
// MythicSim Go sim/core package. It is NOT a substitute for gsim 2D or an
// assertion that native spell action/ACK causality has been demonstrated.
package core

import (
	"errors"
	"fmt"
	"time"
)

// WorldRangeReceipt is an observation of native state after a world position
// was applied. It is NOT a native spell/action ACK or a P7 gate result.
type WorldRangeReceipt struct {
	Sequence              uint64  `json:"sequence"`
	NativeClockNS         int64   `json:"native_clock_ns"`
	PlayerIndex           int     `json:"player_index"`
	AppliedYards          float64 `json:"applied_yards"`
	NativeEncounterDamage float64 `json:"native_encounter_damage"`
}

// WorldBoundarySession holds one genuine Simulation across ordered world ticks.
// The native engine owns spell effects; external world geometry supplies range.
type WorldBoundarySession struct {
	native        *Simulation
	lastTick      time.Duration
	sequence      uint64
	awaitingWorld bool
	started       bool
	worldHealthInitialized bool
	worldHealthMax float64
	worldHealthLast float64
}

func NewWorldBoundarySession(native *Simulation) (*WorldBoundarySession, error) {
	if native == nil || native.Environment == nil || native.Raid == nil {
		return nil, errors.New("NATIVE_WORLD_SESSION_REQUIRES_REAL_SIMULATION")
	}
	return &WorldBoundarySession{native: native}, nil
}

// NativeEncounterEndNS exposes the pinned native engine's sampled source
// encounter duration. The gsim controller must stop at this native clock
// boundary rather than guessing a fixed 120-second endpoint.
func (session *WorldBoundarySession) NativeEncounterEndNS() (int64, error) {
    if session == nil || session.native == nil || session.native.endOfCombatDuration <= 0 {
        return 0, errors.New("NATIVE_WORLD_ENCOUNTER_END_UNAVAILABLE")
    }
    return int64(session.native.endOfCombatDuration), nil
}

// nextWorldNativeEventAt includes all three event sources in Simulation.Step.
// Inspecting only pendingActions would let native autos/tasks jump past a tick.
func (sim *Simulation) nextWorldNativeEventAt() time.Duration {
	next := NeverExpires
	if len(sim.pendingActions) > 0 {
		next = sim.pendingActions[len(sim.pendingActions)-1].NextActionAt
	}
	if sim.minWeaponAttackTime < next {
		next = sim.minWeaponAttackTime
	}
	if sim.minTaskTime < next {
		next = sim.minTaskTime
	}
	return next
}

// AdvanceToWorldTick runs only native events STRICTLY before tick, then
// parks the same native clock at tick WITHOUT processing tracker/execute-phase
// callbacks. Those are advanced only after ApplyWorldDistance. An event at
// tick must see the new world range before it can run.
func (session *WorldBoundarySession) AdvanceToWorldTick(tick time.Duration, maxSteps int) (int, error) {
	if session == nil || session.native == nil {
		return 0, errors.New("NATIVE_WORLD_SESSION_MISSING")
	}
	if session.awaitingWorld {
		return 0, errors.New("PREVIOUS_WORLD_TICK_NOT_APPLIED")
	}
	if err := validateWorldTick(session.lastTick, tick, !session.started); err != nil {
		return 0, err
	}
	sim := session.native
	if tick < sim.CurrentTime {
		return 0, fmt.Errorf("WORLD_TICK_BEHIND_NATIVE_CLOCK: tick=%s native=%s", tick, sim.CurrentTime)
	}
	if tick > sim.endOfCombatDuration {
		return 0, errors.New("WORLD_TICK_AFTER_NATIVE_ENCOUNTER_END")
	}
	if maxSteps < 1 || maxSteps > 1000000 {
		return 0, errors.New("NATIVE_STEP_BUDGET_INVALID")
	}
	steps := 0
	for shouldExecuteNativeEvent(sim.nextWorldNativeEventAt(), tick) {
		if steps == maxSteps {
			return steps, errors.New("NATIVE_STEP_BUDGET_EXHAUSTED_BEFORE_WORLD_TICK")
		}
		if sim.Step() {
			return steps, errors.New("NATIVE_ENCOUNTER_FINISHED_BEFORE_WORLD_TICK")
		}
		steps++
		if sim.CurrentTime > tick {
			return steps, errors.New("NATIVE_CLOCK_OVERRAN_WORLD_TICK")
		}
	}
	if sim.CurrentTime < tick {
		// Do not call sim.advance yet: it can fire aura/execute callbacks at
		// this exact tick before the external world state is applied.
		sim.CurrentTime = tick
	}
	session.awaitingWorld = true
	session.started = true
	session.lastTick = tick
	return steps, nil
}

// Apply the same real native movement and auto-attack bookkeeping both
// during ordinary world ticks and when parking between serial world targets.
func applyWorldDistanceToPlayer(sim *Simulation, unit *Unit, yards float64) {
	old := unit.DistanceFromTarget
	unit.DistanceFromTarget = yards
	if old != yards {
		unit.OnMovement(sim, yards, MovementUpdate)
		// Match upstream Unit.UpdatePosition's auto-attack range bookkeeping;
		// no synthetic movement spell or duplicated travel is introduced.
		if unit.AutoAttacks.mh.enabled != unit.AutoAttacks.mh.IsInRange() {
			if unit.AutoAttacks.mh.IsInRange() {
				unit.AutoAttacks.cancelMeleeWeaveWakeup(sim)
				unit.AutoAttacks.EnableMeleeSwing(sim)
				unit.AutoAttacks.holdArrivalSwingForRotation(sim)
			} else {
				unit.AutoAttacks.CancelMeleeSwing(sim)
				unit.AutoAttacks.scheduleMeleeWeaveWakeup(sim)
			}
		}
		if unit.AutoAttacks.ranged.enabled != unit.AutoAttacks.ranged.IsInRange() {
			if unit.AutoAttacks.ranged.IsInRange() {
				unit.AutoAttacks.EnableRangedSwing(sim)
			} else {
				unit.AutoAttacks.CancelRangedSwing(sim)
			}
		}
	}

}

// ApplyWorldDistance acknowledges only the real native distance mutation.
// The next native event at this timestamp can now run with the new range.
// Full gsim 2D position/facing/CC and native spell action ACK are separate work.
func (session *WorldBoundarySession) ApplyWorldDistance(sequence uint64, playerIndex int, yards float64) (WorldRangeReceipt, error) {
	if session == nil || session.native == nil || !session.awaitingWorld {
		return WorldRangeReceipt{}, errors.New("WORLD_DISTANCE_WITHOUT_PENDING_TICK")
	}
	if sequence != session.sequence {
		return WorldRangeReceipt{}, fmt.Errorf("WORLD_SEQUENCE_MISMATCH: got=%d want=%d", sequence, session.sequence)
	}
	if err := validateWorldDistance(yards); err != nil {
		return WorldRangeReceipt{}, err
	}
	sim := session.native
	if sim.CurrentTime != session.lastTick {
		return WorldRangeReceipt{}, errors.New("NATIVE_CLOCK_CHANGED_BEFORE_WORLD_APPLY")
	}
	if playerIndex < 0 || playerIndex >= len(sim.Raid.AllPlayerUnits) {
		return WorldRangeReceipt{}, errors.New("WORLD_PLAYER_INDEX_INVALID")
	}
	unit := sim.Raid.AllPlayerUnits[playerIndex]
	if unit == nil || unit.Moving {
		return WorldRangeReceipt{}, errors.New("NATIVE_MOVEMENT_CONFLICT_OR_MISSING_PLAYER")
	}
	applyWorldDistanceToPlayer(sim, unit, yards)
	if unit.DistanceNow(sim) != yards {
		return WorldRangeReceipt{}, errors.New("NATIVE_WORLD_DISTANCE_NOT_APPLIED")
	}
	// Run native tracker/execute-phase callbacks at this clock only AFTER
	// applying the external world range, never before the world boundary.
	sim.advance(session.lastTick)
	receipt := WorldRangeReceipt{Sequence: sequence, NativeClockNS: int64(sim.CurrentTime), PlayerIndex: playerIndex, AppliedYards: unit.DistanceNow(sim), NativeEncounterDamage: sim.Encounter.DamageTaken}
	session.sequence++
	session.awaitingWorld = false
	return receipt, nil
}
