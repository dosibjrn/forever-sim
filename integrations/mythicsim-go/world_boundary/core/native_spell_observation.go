// Native combat observations from the pinned Go scheduler's *real* per-spell
// iteration counters. These are NOT event IDs, action-ACKs, or P7 evidence.
package core

import (
    "errors"
    "fmt"
    "math"
    "sort"
)

// WorldNativeSpellCounter is a cumulative native-owned observation. A spell
// may have several targets; aggregate only that registered source spell's real
// SpellMetrics, never derive spell identity from a player-side APL guess.
type WorldNativeSpellCounter struct {
    ActionID string `json:"action_id"`
    Rank int32 `json:"rank"`
    Casts int64 `json:"casts"`
    Hits int64 `json:"hits"`
    Crits int64 `json:"crits"`
    Ticks int64 `json:"ticks"`
    TotalDamage float64 `json:"total_damage"`
}

// NativeSpellCounters reads actual native spell counters from one retained
// Simulation at the CURRENT world boundary. This is not a replay/estimate.
// The counters do NOT contain precise event timestamps or proof a spell changed
// the gsim world. Integration must separately implement world action/ACK.
func (session *WorldBoundarySession) NativeSpellCounters(playerIndex int) ([]WorldNativeSpellCounter, error) {
    if session == nil || session.native == nil || session.native.Raid == nil {
        return nil, errors.New("NATIVE_SPELL_SESSION_UNAVAILABLE")
    }
    if session.awaitingWorld {
        return nil, errors.New("NATIVE_SPELL_WORLD_TICK_NOT_APPLIED")
    }
    if playerIndex < 0 || playerIndex >= len(session.native.Raid.AllPlayerUnits) {
        return nil, errors.New("NATIVE_SPELL_PLAYER_INDEX_INVALID")
    }
    player := session.native.Raid.AllPlayerUnits[playerIndex]
    if player == nil {
        return nil, errors.New("NATIVE_SPELL_PLAYER_MISSING")
    }
    counters := make([]WorldNativeSpellCounter, 0)
    for _, spell := range player.Spellbook {
        if spell == nil {
            continue
        }
        entry := WorldNativeSpellCounter{ActionID: spell.ActionID.String(), Rank: spell.Rank}
        if entry.ActionID == "" {
            return nil, errors.New("NATIVE_SPELL_ACTION_ID_MISSING")
        }
        // A spell can switch its active metrics split while shapeshifting or
        // through a tagged effect. Summing ONLY SpellMetrics (the current split)
        // would make formerly counted native events vanish between world ticks.
        // Each split has independent storage; never count the current alias twice.
        splits := spell.splitSpellMetrics
        if len(splits) == 0 {
            splits = [][]SpellMetrics{spell.SpellMetrics}
        }
        for _, targetMetrics := range splits {
            for _, metrics := range targetMetrics {
                entry.Casts += int64(metrics.Casts)
                entry.Hits += int64(metrics.Hits)
                entry.Crits += int64(metrics.Crits)
                entry.Ticks += int64(metrics.Ticks)
                entry.TotalDamage += metrics.TotalDamage
            }
        }
        if entry.Casts < 0 || entry.Hits < 0 || entry.Crits < 0 ||
            entry.Ticks < 0 || math.IsNaN(entry.TotalDamage) ||
            math.IsInf(entry.TotalDamage, 0) || entry.TotalDamage < 0 {
            return nil, fmt.Errorf("NATIVE_SPELL_COUNTERS_INVALID:%s", entry.ActionID)
        }
        // Include only spells with real observed activity, not source candidates
        // simply registered in the player's Spellbook.
        if entry.Casts > 0 || entry.Hits > 0 || entry.Crits > 0 ||
            entry.Ticks > 0 || entry.TotalDamage > 0 {
            counters = append(counters, entry)
        }
    }
    sort.Slice(counters, func(i, j int) bool {
        if counters[i].ActionID != counters[j].ActionID {
            return counters[i].ActionID < counters[j].ActionID
        }
        return counters[i].Rank < counters[j].Rank
    })
    return counters, nil
}
