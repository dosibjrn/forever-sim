#!/usr/bin/env python3
"""Forward actual gsim 2D walking state into selected source-Rust cast legality.

Source Rust remains the sole owner of casting rules; gsim supplies only its
observed world movement. This small port is an integration staging mechanism,
not a second spell implementation or a paid P4–P6 acceptance path.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _replace(source: str, old: str, new: str, label: str) -> str:
    if source.count(new) == 1 and source.count(old) == 0:
        return source
    if source.count(old) != 1 or new in source:
        raise ValueError(f"RUST_WORLD_MOVING_{label}_ANCHOR_DRIFT")
    return source.replace(old, new, 1)


def port_bridge(source: str) -> str:
    source = _replace(source,
        "pub(crate) fn exchange(clock_ns: i64, duration_ns: i64, cumulative_damage: f64) -> (f64, bool) {",
        "pub(crate) fn exchange(clock_ns: i64, duration_ns: i64, cumulative_damage: f64) -> (f64, bool, bool) {",
        "SIGNATURE")
    source = _replace(source,
        '''    let front = tick["in_front_of_target"].as_bool()
        .expect("RUST_WORLD_FACING_NOT_PROVIDED");
''',
        '''    let front = tick["in_front_of_target"].as_bool()
        .expect("RUST_WORLD_FACING_NOT_PROVIDED");
    // World movement is a live gsim fact, not a native game-rule override.
    let moving = tick["gsim_player_moving"].as_bool()
        .expect("RUST_WORLD_PLAYER_MOVEMENT_NOT_PROVIDED");
''', "INGRESS")
    source = _replace(source,
        '"facing_applied": true, "in_front_of_target": front',
        '"facing_applied": true, "in_front_of_target": front,\n            "gsim_player_moving": moving',
        "MOVING_RECEIPT")
    return _replace(source,
        "    (distance, front)\n}\n",
        "    (distance, front, moving)\n}\n",
        "RESULT")


def port_fight(source: str) -> str:
    source = _replace(source,
        '''                let (distance, front) = world_bridge::exchange(
                    boundary, self.duration, self.encounter_damage_taken);
''',
        '''                let (distance, front, moving) = world_bridge::exchange(
                    boundary, self.duration, self.encounter_damage_taken);
''',
        "EXCHANGE")
    return _replace(source,
        '''                if self.config.melee.in_front_of_target != front {
                    self.config.melee.in_front_of_target = front;
                    self.changed(reads::CASTS);
                }
                return true;
''',
        '''                if self.config.melee.in_front_of_target != front {
                    self.config.melee.in_front_of_target = front;
                    self.changed(reads::CASTS);
                }
                // The source-Rust spell cast rules already test player.moving;
                // use the real gsim route status to enforce them, including
                // between SpatialPlayerMoveStep events, without teleporting.
                if self.player.moving != moving {
                    self.player.moving = moving;
                    self.changed(reads::CASTS);
                }
                return true;
''', "CAST_LEGALITY")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_gsim_moving.py RUST_ENGINE_ROOT")
    root = Path(argv[1]) / "src/core"
    for path, port in ((root / "fight/world_bridge.rs", port_bridge),
                       (root / "fight.rs", port_fight)):
        before = path.read_text()
        after = port(before)
        if after != before:
            path.write_text(after)
    print("RUST_GSIM_MOVING_CAST_LEGALITY_PORTED_OR_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
