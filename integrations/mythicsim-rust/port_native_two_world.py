#!/usr/bin/env python3
"""Expose the selected Rust actor's real two-target gsim boundary, not a second simulator.

The existing native-only two-window command remains unchanged. In world mode,
both kills must come from the actual gsim HP/death/hash ACK before Rust can
retarget; resources and the native event queue stay on the same Fight.
No paid recovery or P4-P6 acceptance is claimed by this diagnostic.
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD_GUARD = '''        if world_bridge::enabled() {
            return Err("RUST_TWO_WINDOW_2D_CONTROLLER_NOT_CONNECTED");
        }
'''
NEW_GUARD = '''        if world_bridge::enabled() {
            return self.native_two_gsim_world_kills();
        }
'''
FIGHT_MARKER = "    /// Begin a second distinct world target on the SAME native actor.\n"
METHOD_MARKER = "    fn native_two_gsim_world_kills(&mut self)"
METHOD = '''    /// Execute two distinct real gsim target deaths with one native Fight.
    /// The external world selects the next mob; Rust retains its actor and ACK
    /// lineage and will not continue without the first native-caused death.
    /// There is only a 1ms causal handoff here: paid travel/recovery is future work.
    fn native_two_gsim_world_kills(&mut self)
        -> Result<serde_json::Value, &'static str>
    {
        if !world_bridge::enabled() {
            return Err("RUST_TWO_WORLD_BRIDGE_DISABLED");
        }
        if !self.extra_targets_built {
            self.build_extra_targets();
            self.build_exclusive_tracking();
            self.apply_enemy_slow_priorities();
        }
        self.rng.reseed(self.config.seed as u64);
        self.log = None;
        self.prepare_first_native_pull();
        while self.step() {}
        if !world_bridge::acknowledged_lethal() {
            return Err("RUST_TWO_WORLD_FIRST_TARGET_NOT_KILLED");
        }
        let first_end_ns = self.now;
        world_bridge::finish(first_end_ns, self.encounter_damage_taken);
        let first = serde_json::json!({
            "index": 0, "end_ns": first_end_ns,
            "actor_mana": self.player.mana, "actor_health": self.player.health,
        });

        // Rust must switch strictly AFTER the last committed gsim ACK tick.
        // Do not reset player, RNG, cooldowns, queued native events or bridge.
        let second_start_ns = first_end_ns.checked_add(1_000_000)
            .ok_or("RUST_TWO_WORLD_CLOCK_OVERFLOW")?;
        let second_cap_ns = second_start_ns.checked_add(self.config.base_duration)
            .ok_or("RUST_TWO_WORLD_DURATION_OVERFLOW")?;
        self.begin_next_target(second_start_ns, second_cap_ns)?;
        while self.step() {}
        if !world_bridge::acknowledged_lethal() {
            return Err("RUST_TWO_WORLD_SECOND_TARGET_NOT_KILLED");
        }
        let second_end_ns = self.now;
        world_bridge::finish(second_end_ns, self.encounter_damage_taken);
        let second = serde_json::json!({
            "index": 1, "start_ns": second_start_ns, "end_ns": second_end_ns,
            "actor_mana": self.player.mana, "actor_health": self.player.health,
        });
        let report = serde_json::json!({
            "scope": "TWO_REAL_GSIM_WORLD_KILLS_DIAGNOSTIC_NOT_GATE",
            "selected_native_combat": true,
            "actual_2d_ack": true, "paid_recovery": false,
            "continuous_actor": true, "windows": [first, second],
        });
        self.cleanup();
        Ok(report)
    }

'''
PREPARED_OLD = '''    check(prepared)?;
    crate::classes::native_two_pull_windows(prepared).map_err(PreparedError::Invalid)
'''
PREPARED_NEW = '''    check(prepared)?;
    if crate::core::fight::world_bridge::enabled() {
        crate::core::fight::world_bridge::start(&prepared.request_sha256);
    }
    crate::classes::native_two_pull_windows(prepared).map_err(PreparedError::Invalid)
'''


def port_fight(source: str) -> str:
    if NEW_GUARD in source and source.count(METHOD) == 1:
        if OLD_GUARD in source or source.count(NEW_GUARD) != 1:
            raise ValueError("RUST_TWO_WORLD_PARTIAL_FIGHT_PORT")
        return source
    if (source.count(OLD_GUARD) != 1 or source.count(FIGHT_MARKER) != 1
            or METHOD_MARKER in source or NEW_GUARD in source):
        raise ValueError("RUST_TWO_WORLD_FIGHT_ANCHOR_DRIFT")
    source = source.replace(OLD_GUARD, NEW_GUARD, 1)
    return source.replace(FIGHT_MARKER, METHOD + FIGHT_MARKER, 1)


def port_prepared(source: str) -> str:
    if PREPARED_NEW in source and PREPARED_OLD not in source:
        if source.count(PREPARED_NEW) != 1:
            raise ValueError("RUST_TWO_WORLD_PARTIAL_PREPARED_PORT")
        return source
    if source.count(PREPARED_OLD) != 1 or PREPARED_NEW in source:
        raise ValueError("RUST_TWO_WORLD_PREPARED_ANCHOR_DRIFT")
    return source.replace(PREPARED_OLD, PREPARED_NEW, 1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_two_world.py RUST_ENGINE_ROOT")
    root = Path(argv[1])
    changed = 0
    for rel, patch in (("src/core/fight.rs", port_fight),
                       ("src/engine/prepared.rs", port_prepared)):
        file = root / rel
        before = file.read_text()
        after = patch(before)
        if before != after:
            file.write_text(after)
            changed += 1
    print("RUST_TWO_GSIM_WORLD_SOURCE_PORTED" if changed
          else "RUST_TWO_GSIM_WORLD_SOURCE_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
