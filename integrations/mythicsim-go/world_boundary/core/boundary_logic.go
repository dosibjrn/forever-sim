package core

import (
	"fmt"
	"math"
	"time"
)

// These guards are shared by the actual pinned-Go scheduler overlay. They are
// independently testable without constructing a fake combat engine.
func validateWorldTick(previous, next time.Duration, first bool) error {
	if next < 0 || (!first && next <= previous) {
		return fmt.Errorf("WORLD_TICK_NOT_MONOTONIC: previous=%s next=%s", previous, next)
	}
	return nil
}

func validateWorldDistance(yards float64) error {
	if math.IsNaN(yards) || math.IsInf(yards, 0) || yards < 0 {
		return fmt.Errorf("WORLD_DISTANCE_INVALID: %v", yards)
	}
	return nil
}

// A native event at exactly the world tick must observe the newly ACKed world
// state, not the previous tick's range. Never use <= here.
func shouldExecuteNativeEvent(nextNative, nextWorld time.Duration) bool {
	return nextNative < nextWorld
}
