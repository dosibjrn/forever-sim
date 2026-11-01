package main

import (
	"fmt"
	"math"
)

// stepObservation is sampled from the same native Go Simulation object after
// an actual core.Simulation.Step call. This is NOT a gsim 2D action or ACK.
type stepObservation struct {
	Step        int     `json:"step"`
	ClockNS     int64   `json:"clock_ns"`
	DamageTaken float64 `json:"encounter_damage_taken"`
}

func validateTransition(before, after stepObservation) error {
	if after.Step != before.Step+1 {
		return fmt.Errorf("NATIVE_STEP_SEQUENCE: %d -> %d", before.Step, after.Step)
	}
	if after.ClockNS < before.ClockNS {
		return fmt.Errorf("NATIVE_CLOCK_REGRESSION: %d -> %d", before.ClockNS, after.ClockNS)
	}
	if math.IsNaN(after.DamageTaken) || math.IsInf(after.DamageTaken, 0) || after.DamageTaken < before.DamageTaken-1e-8 {
		return fmt.Errorf("NATIVE_DAMAGE_REGRESSION_OR_INVALID: %.8f -> %.8f", before.DamageTaken, after.DamageTaken)
	}
	return nil
}

func validateCompletedTrace(start, last stepObservation, steps int, finished bool) error {
	if steps < 2 || last.Step != steps {
		return fmt.Errorf("TOO_FEW_NATIVE_STEPS_OR_INCOMPLETE_TRACE: %d", steps)
	}
	if !finished {
		return fmt.Errorf("NATIVE_FIGHT_NOT_FINISHED_WITHIN_STEP_BUDGET: %d", steps)
	}
	if last.ClockNS <= start.ClockNS && last.DamageTaken <= start.DamageTaken {
		return fmt.Errorf("NO_NATIVE_PROGRESS")
	}
	return nil
}
