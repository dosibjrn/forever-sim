// Standalone JSONL contract for real gsim world range ticks. Not P7 evidence.
package main

import (
    "bytes"
    "encoding/hex"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "math"
)

const protocol = "gsim-go-range-v1"

type worldTick struct {
    Type string `json:"type"`
    Protocol string `json:"protocol"`
    Sequence uint64 `json:"sequence"`
    ClockMS int64 `json:"clock_ms"`
    NativeClockNS int64 `json:"native_clock_ns"`
    NativePlayerIndex int `json:"native_player_index"`
    WorldSHA256 string `json:"world_sha256"`
    PreviousWorldACKID string `json:"previous_world_ack_id"`
    SelectedTargetID string `json:"selected_target_id"`
    DistanceYards float64 `json:"distance_yards"`
    WorldTargetHealthBefore float64 `json:"world_target_health_before"`
    WorldTargetMaxHealth float64 `json:"world_target_max_health"`
    WorldSource string `json:"world_source"`
    RangeOnly bool `json:"range_only"`
    FacingApplied bool `json:"facing_applied"`
    ControlsApplied bool `json:"controls_applied"`
    NativeActionACK bool `json:"native_action_ack"`
    CheckpointCertified bool `json:"checkpoint_certified"`
}

type tickValidator struct { next uint64; lastClock int64; started bool }

func decodeWorldTick(line []byte) (worldTick, error) {
    var tick worldTick
    decoder := json.NewDecoder(bytes.NewReader(line))
    decoder.DisallowUnknownFields()
    if err := decoder.Decode(&tick); err != nil { return tick, err }
    var leftover interface{}
    if err := decoder.Decode(&leftover); err != io.EOF { return tick, errors.New("WORLD_TICK_TRAILING_JSON") }
    return tick, nil
}

func (v *tickValidator) validate(t worldTick) error {
    if t.Type != "gsim_world_range_tick" || t.Protocol != protocol || t.WorldSource != "gsim.CombatRuntime" {
        return errors.New("WORLD_TICK_PROTOCOL_OR_SOURCE_INVALID")
    }
    if t.Sequence != v.next || t.ClockMS < 0 || (v.started && t.ClockMS <= v.lastClock) {
        return fmt.Errorf("WORLD_TICK_REPLAY_OR_CLOCK_ROLLBACK: sequence=%d clock=%d", t.Sequence, t.ClockMS)
    }
    if t.ClockMS > math.MaxInt64/1000000 || t.NativeClockNS != t.ClockMS*1000000 {
        return errors.New("WORLD_TICK_NATIVE_CLOCK_MISMATCH")
    }
    if t.NativePlayerIndex < 0 || t.SelectedTargetID == "" || !t.RangeOnly || t.FacingApplied || t.ControlsApplied || t.NativeActionACK || t.CheckpointCertified {
        return errors.New("WORLD_TICK_UNPROVEN_SEMANTICS")
    }
    if math.IsNaN(t.DistanceYards) || math.IsInf(t.DistanceYards, 0) || t.DistanceYards < 0 {
        return errors.New("WORLD_TICK_DISTANCE_INVALID")
    }
    if math.IsNaN(t.WorldTargetHealthBefore) || math.IsInf(t.WorldTargetHealthBefore,0) ||
        math.IsNaN(t.WorldTargetMaxHealth) || math.IsInf(t.WorldTargetMaxHealth,0) ||
        t.WorldTargetMaxHealth<=0 || t.WorldTargetHealthBefore<=0 ||
        t.WorldTargetHealthBefore>t.WorldTargetMaxHealth {
        return errors.New("WORLD_TICK_TARGET_HEALTH_INVALID")
    }
    digest, err := hex.DecodeString(t.WorldSHA256)
    if err != nil || len(digest) != 32 || len(t.WorldSHA256) != 64 {
        return errors.New("WORLD_TICK_HASH_INVALID")
    }
    // Source string and digest are assertions by the gsim producer, not proof
    // that caller did not invent JSON. Never promote to combat causality.
    v.lastClock = t.ClockMS
    v.started = true
    v.next++
    return nil
}


// The selected gsim target is fixed until its lethal world ACK is accepted.
// A subsequent pull may use the same retained native enemy slot, but the
// target identity must actually change; a fake world hash is not permission
// to silently retarget a living enemy.
func validateWorldTargetTransition(previous string, lethalACK bool, selected string) error {
    if previous=="" {
        if lethalACK {return errors.New("WORLD_TARGET_TRANSITION_WITHOUT_FIRST_TARGET")}
        return nil
    }
    if lethalACK {
        if selected==previous {return errors.New("WORLD_NEXT_TARGET_MUST_DIFFER_FROM_DEAD_TARGET")}
    } else if selected!=previous {
        return errors.New("WORLD_TARGET_SWITCH_WITHOUT_LETHAL_ACK")
    }
    return nil
}

 // Before the next native scheduler step, the gsim tick must continue from
 // the last world-effect ACK. The native health API already enforces this,
 // but only AFTER gsim damage has been applied; fail before any side effects.
func validateWorldHealthContinuity(t worldTick, previousTarget string, previousDead bool,
    previousAfter, previousMax float64, hasACK bool) error {
    if !hasACK || previousDead { return nil }
    if t.SelectedTargetID != previousTarget {
        return errors.New("WORLD_TARGET_SWITCH_WITHOUT_LETHAL_ACK")
    }
    if math.Abs(t.WorldTargetHealthBefore-previousAfter)>1e-6 ||
        math.Abs(t.WorldTargetMaxHealth-previousMax)>1e-6 {
        return errors.New("WORLD_HEALTH_CHANGED_WITHOUT_NATIVE_ACK")
    }
    return nil
}
