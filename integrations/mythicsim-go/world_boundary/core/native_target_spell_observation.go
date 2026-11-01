// Explicit native-enemy-index spell metrics for source-backed world action mapping.
// This is a native *observation*, NOT exact-time damage events or world ACK.
package core

import (
    "errors"
    "fmt"
    "math"
    "sort"
)

type WorldNativeTargetSpellCounter struct {
    ActionID string `json:"action_id"`
    Rank int32 `json:"rank"`
    NativeTargetIndex int32 `json:"native_target_index"`
    NativeTargetUnitIndex int32 `json:"native_target_unit_index"`
    NativeTargetLabel string `json:"native_target_label"`
    Casts int64 `json:"casts"`
    Hits int64 `json:"hits"`
    Crits int64 `json:"crits"`
    Ticks int64 `json:"ticks"`
    TotalDamage float64 `json:"total_damage"`
}

// Reconcile exact registered *native target* metrics, never assume all
// spellbook damage was addressed to gsim's currently selected target.
// Current bridge permits ONLY one native enemy: multiple enemy scenarios
// need explicit native-target ↔ gsim-target identities before application.
func (session *WorldBoundarySession) NativeSingleTargetSpellCounters(playerIndex int) ([]WorldNativeTargetSpellCounter,error) {
    if session == nil || session.native == nil || session.native.Raid == nil {
        return nil, errors.New("NATIVE_TARGET_SPELL_SESSION_MISSING")
    }
    if session.awaitingWorld {
        return nil, errors.New("NATIVE_TARGET_SPELL_WORLD_ACK_PENDING")
    }
    sim := session.native
    if len(sim.Encounter.ActiveTargetUnits) != 1 {
        return nil, errors.New("NATIVE_TARGET_SPELL_REQUIRES_ONE_ACTIVE_ENEMY")
    }
    target := sim.Encounter.ActiveTargetUnits[0]
    if target == nil || target.Type != EnemyUnit || target.Index != 0 || target.Label == "" {
        return nil, errors.New("NATIVE_TARGET_IDENTITY_UNVERIFIED")
    }
    if playerIndex < 0 || playerIndex >= len(sim.Raid.AllPlayerUnits) || sim.Raid.AllPlayerUnits[playerIndex] == nil {
        return nil, errors.New("NATIVE_TARGET_SPELL_PLAYER_INDEX_INVALID")
    }
    targetSlot := int(target.UnitIndex)
    if targetSlot < 0 {
        return nil, errors.New("NATIVE_TARGET_UNIT_INDEX_INVALID")
    }
    player := sim.Raid.AllPlayerUnits[playerIndex]
    rows := make([]WorldNativeTargetSpellCounter, 0)
    for _, spell := range player.Spellbook {
        if spell == nil { continue }
        entry := WorldNativeTargetSpellCounter{
            ActionID:spell.ActionID.String(),Rank:spell.Rank,
            NativeTargetIndex:target.Index,NativeTargetUnitIndex:target.UnitIndex,
            NativeTargetLabel:target.Label,
        }
        splits := spell.splitSpellMetrics
        if len(splits) == 0 {
            splits = [][]SpellMetrics{spell.SpellMetrics}
        }
        for _, split := range splits {
            if targetSlot >= len(split) {
                return nil, fmt.Errorf("NATIVE_TARGET_METRIC_SLOT_MISSING:%s",entry.ActionID)
            }
            m := split[targetSlot]
            entry.Casts += int64(m.Casts)
            entry.Hits += int64(m.Hits)
            entry.Crits += int64(m.Crits)
            entry.Ticks += int64(m.Ticks)
            entry.TotalDamage += m.TotalDamage
        }
        if entry.Casts < 0 || entry.Hits < 0 || entry.Crits < 0 || entry.Ticks < 0 ||
            math.IsNaN(entry.TotalDamage) || math.IsInf(entry.TotalDamage,0) || entry.TotalDamage < 0 {
            return nil, fmt.Errorf("NATIVE_TARGET_SPELL_COUNTER_INVALID:%s",entry.ActionID)
        }
        if entry.Casts > 0 || entry.Hits > 0 || entry.Crits > 0 || entry.Ticks > 0 || entry.TotalDamage > 0 {
            rows = append(rows,entry)
        }
    }
    sort.Slice(rows,func(i,j int)bool {
        if rows[i].ActionID != rows[j].ActionID {return rows[i].ActionID<rows[j].ActionID}
        return rows[i].Rank<rows[j].Rank
    })
    return rows,nil
}
