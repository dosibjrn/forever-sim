package main

import (
	"strings"
	"testing"
)

func TestStepTransitionRejectsClockRollback(t *testing.T) {
	before := stepObservation{Step: 3, ClockNS: 100, DamageTaken: 10}
	after := stepObservation{Step: 4, ClockNS: 99, DamageTaken: 11}
	if err := validateTransition(before, after); err == nil || !strings.Contains(err.Error(), "CLOCK_REGRESSION") {
		t.Fatalf("expected clock rollback rejection, got %v", err)
	}
}

func TestStepTransitionRejectsDamageRollback(t *testing.T) {
	before := stepObservation{Step: 1, ClockNS: 100, DamageTaken: 10}
	after := stepObservation{Step: 2, ClockNS: 110, DamageTaken: 9}
	if err := validateTransition(before, after); err == nil || !strings.Contains(err.Error(), "DAMAGE_REGRESSION") {
		t.Fatalf("expected damage rollback rejection, got %v", err)
	}
}

func TestStepTransitionRequiresActualConsecutiveNativeStep(t *testing.T) {
	before := stepObservation{Step: 1, ClockNS: 100, DamageTaken: 10}
	after := stepObservation{Step: 3, ClockNS: 110, DamageTaken: 11}
	if err := validateTransition(before, after); err == nil || !strings.Contains(err.Error(), "STEP_SEQUENCE") {
		t.Fatalf("expected missing step rejection, got %v", err)
	}
}

func TestStepTransitionAllowsSameClockEventAndDamageProgress(t *testing.T) {
	before := stepObservation{Step: 1, ClockNS: 100, DamageTaken: 10}
	after := stepObservation{Step: 2, ClockNS: 100, DamageTaken: 11}
	if err := validateTransition(before, after); err != nil {
		t.Fatalf("legitimate same-timestamp native event rejected: %v", err)
	}
}

func TestCompletedTraceRequiresNativeProgressAndTermination(t *testing.T) {
	start := stepObservation{Step: 0, ClockNS: 0}
	progressed := stepObservation{Step: 4, ClockNS: 100, DamageTaken: 3}
	for _, tc := range []struct {
		name   string
		steps  int
		done   bool
		last   stepObservation
		reason string
	}{
		{"too_short", 1, true, progressed, "TOO_FEW"},
		{"unfinished", 4, false, progressed, "NOT_FINISHED"},
		{"no_progress", 4, true, stepObservation{Step: 4}, "NO_NATIVE_PROGRESS"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if err := validateCompletedTrace(start, tc.last, tc.steps, tc.done); err == nil || !strings.Contains(err.Error(), tc.reason) {
				t.Fatalf("expected %s, got %v", tc.reason, err)
			}
		})
	}
	if err := validateCompletedTrace(start, progressed, 4, true); err != nil {
		t.Fatalf("real scheduler progress should be accepted: %v", err)
	}
}
