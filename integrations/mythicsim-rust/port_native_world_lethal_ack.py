#!/usr/bin/env python3
"""Require a lethal source-native world ACK before retargeting the Rust actor.

Ports a fail-closed check into the real maintained Rust world bridge. The next
mob may only start after gsim acknowledged native damage which killed the
previous target. No Python combat rules or separate world simulator.
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD = """        if !bridge.pending.is_empty() {
            return Err("RUST_WORLD_UNACKNOWLEDGED_DAMAGE");
        }
        if at_ns <= bridge.last_tick_ns || at_ns < 0 {
"""
NEW = """        if !bridge.pending.is_empty() {
            return Err("RUST_WORLD_UNACKNOWLEDGED_DAMAGE");
        }
        // A free world-target switch would silently turn time-bounded fights
        // into fabricated mob kills. The preceding real source damage must
        // have received a gsim HP/death/hash ACK before a new target is legal.
        if bridge.sequence == 0 || bridge.previous_ack_id.len() != 64
            || bridge.last_health != Some(0.0) {
            return Err("RUST_WORLD_NEXT_TARGET_NOT_NATIVE_LETHAL");
        }
        if at_ns <= bridge.last_tick_ns || at_ns < 0 {
"""
TEST_MARKER = "mod persistent_next_target_world_lethal_ack_tests"
TESTS = """#[cfg(test)]
mod persistent_next_target_world_lethal_ack_tests {
    use super::*;

    #[test]
    fn persistent_next_target_requires_real_lethal_world_ack() {
        // This is the live Rust bridge's real state machine, not a replacement
        // combat evaluator. Only exchange() can set these ACK-derived fields
        // in production.
        BRIDGE.with(|slot| *slot.borrow_mut() = Some(Bridge {
            iteration: 0, sequence: 1, next_tick_ns: 200,
            last_tick_ns: 100, last_health: Some(25.0),
            previous_ack_id: "a".repeat(64), source_hash: "b".repeat(64),
            event_ordinal: 9, pending: Vec::new(),
        }));
        assert_eq!(begin_next_target(200),
            Err("RUST_WORLD_NEXT_TARGET_NOT_NATIVE_LETHAL"));
        BRIDGE.with(|slot| {
            let mut state = slot.borrow_mut();
            let state = state.as_mut().unwrap();
            state.last_health = Some(0.0);
            state.previous_ack_id.clear();
        });
        assert_eq!(begin_next_target(200),
            Err("RUST_WORLD_NEXT_TARGET_NOT_NATIVE_LETHAL"));
        BRIDGE.with(|slot| slot.borrow_mut().as_mut().unwrap()
            .previous_ack_id = "a".repeat(64));
        assert_eq!(begin_next_target(200), Ok(()));
        BRIDGE.with(|slot| {
            let state = slot.borrow();
            let state = state.as_ref().unwrap();
            assert_eq!(state.iteration, 1);
            assert_eq!(state.sequence, 1);
            assert_eq!(state.event_ordinal, 9);
            assert_eq!(state.previous_ack_id, "a".repeat(64));
            assert_eq!(state.last_tick_ns, 100);
            assert_eq!(state.next_tick_ns, 200);
            assert_eq!(state.last_health, None);
        });
        // The new target cannot be skipped without its own lethal ACK.
        assert_eq!(begin_next_target(300),
            Err("RUST_WORLD_NEXT_TARGET_NOT_NATIVE_LETHAL"));
    }
}

"""
BEFORE_TEST = "pub(crate) fn due(next_native_ns: i64, end_ns: i64) -> Option<i64> {"


def port_source(source: str) -> str:
    if NEW in source:
        if (source.count(NEW) != 1 or source.count(TEST_MARKER) != 1
                or source.count(TESTS) != 1):
            raise ValueError("Rust lethal-ACK port partially applied")
        return source
    if source.count(OLD) != 1:
        raise ValueError("Rust world retarget source anchor missing or ambiguous")
    if TEST_MARKER in source or source.count(BEFORE_TEST) != 1:
        raise ValueError("Rust world retarget tests/entry anchor changed")
    updated = source.replace(OLD, NEW, 1)
    return updated.replace(BEFORE_TEST, TESTS + BEFORE_TEST, 1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_world_lethal_ack.py RUST_ENGINE_ROOT")
    file = Path(argv[1]) / "src/core/fight/world_bridge.rs"
    before = file.read_text()
    after = port_source(before)
    if after != before:
        file.write_text(after)
        print("RUST_NATIVE_WORLD_LETHAL_ACK_GUARD_PORTED")
    else:
        print("RUST_NATIVE_WORLD_LETHAL_ACK_GUARD_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
