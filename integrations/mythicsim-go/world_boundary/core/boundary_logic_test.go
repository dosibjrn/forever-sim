package core

import (
	"math"
	"strings"
	"testing"
	"time"
)

func TestWorldTickRejectsRollbackAndDuplicate(t *testing.T) {
	for _, next := range []time.Duration{9 * time.Millisecond, 10 * time.Millisecond} {
		if err := validateWorldTick(10*time.Millisecond, next, false); err == nil || !strings.Contains(err.Error(), "WORLD_TICK_NOT_MONOTONIC") {
			t.Fatalf("expected monotonic error at %v: %v", next, err)
		}
	}
	if err := validateWorldTick(10*time.Millisecond, 11*time.Millisecond, false); err != nil {
		t.Fatal(err)
	}
	if err := validateWorldTick(0, 0, true); err != nil {
		t.Fatal(err)
	}
	if err := validateWorldTick(0, -time.Nanosecond, true); err == nil {
		t.Fatal("negative first tick accepted")
	}
}

func TestWorldDistanceRejectsInvalid(t *testing.T) {
	for _, d := range []float64{-1, math.NaN(), math.Inf(1), math.Inf(-1)} {
		if validateWorldDistance(d) == nil {
			t.Fatalf("accepted %v", d)
		}
	}
	if err := validateWorldDistance(0); err != nil {
		t.Fatal(err)
	}
	if err := validateWorldDistance(42.5); err != nil {
		t.Fatal(err)
	}
}

func TestWorldBoundaryNeverExecutesEventAtBoundary(t *testing.T) {
	at := 100 * time.Millisecond
	if !shouldExecuteNativeEvent(at-time.Nanosecond, at) {
		t.Fatal("pre-boundary event skipped")
	}
	if shouldExecuteNativeEvent(at, at) {
		t.Fatal("same-clock native event executed before world ACK")
	}
	if shouldExecuteNativeEvent(at+time.Nanosecond, at) {
		t.Fatal("future native event executed")
	}
}
