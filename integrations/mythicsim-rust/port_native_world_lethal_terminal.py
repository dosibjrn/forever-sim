#!/usr/bin/env python3
"""Let a real native-damage -> gsim lethal ACK terminate the selected Rust pull.

The native actor's final reported duration must be the measured world kill
clock, not the source encounter's unused fixed-duration tail. This ports a
small Rust source change; it introduces no Python combat mechanics, no second
engine, and no claim of 2D two-target or 100-mob acceptance.
"""
from __future__ import annotations

import sys
from pathlib import Path

FIGHT_LOOP_OLD = """        while self.step() {}
        if world_bridge::enabled() { world_bridge::finish(self.duration, self.encounter_damage_taken); }
        self.cleanup();
"""
FIGHT_LOOP_NEW = """        while self.step() {}
        // A real applied gsim lethal ACK ends this pull even if the saved
        // encounter's duration has not elapsed. Preserve the actual world
        // clock in the native result rather than charging an unplayed tail.
        if world_bridge::enabled() && world_bridge::acknowledged_lethal() {
            self.duration = self.now.max(1);
        }
        if world_bridge::enabled() { world_bridge::finish(self.duration, self.encounter_damage_taken); }
        self.cleanup();
"""
STEP_OLD = """    fn step(&mut self) -> bool {
        if world_bridge::enabled() {
"""
STEP_NEW = """    fn step(&mut self) -> bool {
        // A committed source-native lethal world ACK must stop scheduling
        // attacks on the now-dead target. The same actor may later be
        // continued explicitly using begin_next_target, without a reset.
        if world_bridge::enabled() && world_bridge::acknowledged_lethal() {
            return false;
        }
        if world_bridge::enabled() {
"""
BRIDGE_ANCHOR = "pub(crate) fn finish(duration_ns: i64, cumulative_damage: f64) {\n"
BRIDGE_FUNCTION = """pub(crate) fn acknowledged_lethal() -> bool {
    BRIDGE.with(|state| {
        let state = state.borrow();
        let bridge = state.as_ref().expect("RUST_WORLD_NOT_STARTED");
        bridge.sequence > 0 && bridge.last_health == Some(0.0)
            && bridge.previous_ack_id.len() == 64 && bridge.pending.is_empty()
    })
}

"""
FINISH_OLD = """    let clock = ((duration_ns + 999_999) / 1_000_000) * 1_000_000;
    let last = BRIDGE.with(|state| state.borrow().as_ref()
        .expect("RUST_WORLD_NOT_STARTED").last_tick_ns);
    let clock = clock.max(last + 1_000_000);
    let _ = exchange(clock, duration_ns, cumulative_damage);
"""
FINISH_NEW = """    let last = BRIDGE.with(|state| state.borrow().as_ref()
        .expect("RUST_WORLD_NOT_STARTED").last_tick_ns);
    if acknowledged_lethal() {
        // gsim has already applied the last native event and killed the mob.
        // Another range tick would address a dead world target and violate
        // the causal ACK sequence. No fabricated terminal world exchange.
        assert!(duration_ns == last, "RUST_WORLD_LETHAL_DURATION_NOT_ACK_CLOCK");
    } else {
        let clock = ((duration_ns + 999_999) / 1_000_000) * 1_000_000;
        let clock = clock.max(last + 1_000_000);
        let _ = exchange(clock, duration_ns, cumulative_damage);
    }
"""
TEST_MARKER = "mod world_lethal_terminal_tests"
TESTS = """#[cfg(test)]
mod world_lethal_terminal_tests {
    use super::*;

    #[test]
    fn world_lethal_terminal_requires_committed_native_world_ack() {
        BRIDGE.with(|state| *state.borrow_mut() = Some(Bridge {
            iteration: 0, sequence: 1, next_tick_ns: 200,
            last_tick_ns: 100, last_health: Some(10.0),
            previous_ack_id: "a".repeat(64), source_hash: "b".repeat(64),
            event_ordinal: 1, pending: Vec::new(),
        }));
        assert!(!acknowledged_lethal());
        BRIDGE.with(|state| state.borrow_mut().as_mut().unwrap().last_health = Some(0.0));
        assert!(acknowledged_lethal());
        BRIDGE.with(|state| state.borrow_mut().as_mut().unwrap().previous_ack_id.clear());
        assert!(!acknowledged_lethal());
        BRIDGE.with(|state| *state.borrow_mut() = None);
    }
}

"""

def replace_exact(source: str, old: str, new: str, name: str) -> str:
    if source.count(new) == 1 and source.count(old) == 0:
        return source
    if source.count(old) != 1 or new in source:
        raise ValueError(f"RUST_WORLD_LETHAL_TERMINAL_{name}_ANCHOR_DRIFT")
    return source.replace(old, new, 1)


def port_fight(source: str) -> str:
    source = replace_exact(source, FIGHT_LOOP_OLD, FIGHT_LOOP_NEW, "LOOP")
    return replace_exact(source, STEP_OLD, STEP_NEW, "STEP")


def port_bridge(source: str) -> str:
    if BRIDGE_FUNCTION not in source:
        if source.count(BRIDGE_ANCHOR) != 1 or "pub(crate) fn acknowledged_lethal()" in source:
            raise ValueError("RUST_WORLD_LETHAL_TERMINAL_BRIDGE_ANCHOR_DRIFT")
        source = source.replace(BRIDGE_ANCHOR, BRIDGE_FUNCTION + BRIDGE_ANCHOR, 1)
    elif source.count(BRIDGE_FUNCTION) != 1:
        raise ValueError("RUST_WORLD_LETHAL_TERMINAL_BRIDGE_PARTIAL")
    source = replace_exact(source, FINISH_OLD, FINISH_NEW, "FINISH")
    before_tests = "pub(crate) fn due(next_native_ns: i64, end_ns: i64) -> Option<i64> {"
    if TESTS not in source:
        if source.count(before_tests) != 1 or TEST_MARKER in source:
            raise ValueError("RUST_WORLD_LETHAL_TERMINAL_TEST_ANCHOR_DRIFT")
        source = source.replace(before_tests, TESTS + before_tests, 1)
    elif source.count(TESTS) != 1:
        raise ValueError("RUST_WORLD_LETHAL_TERMINAL_TEST_PARTIAL")
    return source


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_world_lethal_terminal.py RUST_ENGINE_ROOT")
    root = Path(argv[1]) / "src/core"
    changes = 0
    for path, port in ((root / "fight.rs", port_fight),
                       (root / "fight/world_bridge.rs", port_bridge)):
        before = path.read_text()
        after = port(before)
        if after != before:
            path.write_text(after)
            changes += 1
    print("RUST_WORLD_LETHAL_TERMINAL_PORTED" if changes else
          "RUST_WORLD_LETHAL_TERMINAL_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
