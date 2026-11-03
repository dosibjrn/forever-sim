#!/usr/bin/env python3
"""Allow an early real-world lethal ACK to end a Rust mob before its time cap.

The selected Rust actor owns the combat scheduler. A fixed-duration window
is a maximum, not a requirement to keep hitting an already killed world mob.
The separate Rust world bridge still requires a lethal, hash-bound gsim ACK
before begin_next_target can actually change targets.
"""
from __future__ import annotations
from pathlib import Path
import sys

OLD_GUARD = """        if at_ns != self.end_of_combat || at_ns < self.now || next_end_ns <= at_ns {
            return Err("RUST_NEXT_TARGET_CLOCK_INVALID");
        }
"""
NEW_GUARD = """        if !self.accepts_next_target_clock(at_ns, next_end_ns, world_bridge::enabled()) {
            return Err("RUST_NEXT_TARGET_CLOCK_INVALID");
        }
"""
HELPER = """    /// Native-only duration windows continue at the old exact end timestamp.
    /// A live world may kill its target earlier, but only the separate
    /// world_bridge::begin_next_target() validates the actual lethal ACK.
    fn accepts_next_target_clock(&self, at_ns: i64, next_end_ns: i64,
        live_world: bool) -> bool
    {
        at_ns >= self.now && at_ns >= 0 && next_end_ns > at_ns
            && (if live_world { at_ns <= self.end_of_combat }
                else { at_ns == self.end_of_combat })
    }

"""
TEST_MARKER = "fn native_persistent_early_world_kill_clock_boundary()"
TEST = """    #[test]
    fn native_persistent_early_world_kill_clock_boundary() {
        let prepared: crate::contracts::prepared_v2::PreparedV2 = serde_json::from_str(
            include_str!(concat!(env!("CARGO_MANIFEST_DIR"),
                "/fixtures/mage/prepared-v2/balance-druid-revelation.prepared.json"))
        ).unwrap();
        let mut fight = crate::classes::druid::agent::DruidAgent::fight(&prepared).unwrap();
        fight.prepare_first_native_pull();
        let now = fight.now;
        let cap = fight.end_of_combat;
        assert!(cap > now + 2_000_000);
        let early = now + 1_000_000;
        // A real early gsim world kill can be the next pull timestamp,
        // but the unchanged native-only duration-window cannot.
        assert!(fight.accepts_next_target_clock(early, early + 2_000_000, true));
        assert!(!fight.accepts_next_target_clock(early, early + 2_000_000, false));
        assert!(fight.accepts_next_target_clock(cap, cap + 2_000_000, false));
        assert!(!fight.accepts_next_target_clock(cap + 1, cap + 2_000_000, true));
        assert!(!fight.accepts_next_target_clock(now - 1, cap + 1, true));
        assert!(!fight.accepts_next_target_clock(early, early, true));
        // This test does not fake a lethal source event or certify a hybrid mob.
    }

"""
METHOD_MARKER = "    pub(crate) fn begin_next_target(&mut self, at_ns: i64, next_end_ns: i64)"
TEST_ANCHOR = "    fn native_persistent_next_target_retains_actor_and_native_queue()"


def port_source(source: str) -> str:
    if source.count("world_bridge::begin_next_target(at_ns)?;") != 1:
        raise ValueError("Rust early-world-target source anchors missing or ambiguous")
    if NEW_GUARD in source:
        typed_rng_test = TEST.replace(
            "DruidAgent::fight(&prepared)",
            "DruidAgent::fight(&prepared, crate::core::rng::RngMode::Stochastic)",
            1,
        )
        descendant_counts = {
            "new_guard": source.count(NEW_GUARD),
            "helper": source.count(HELPER),
            "untyped_test": source.count(TEST),
            "typed_rng_test": source.count(typed_rng_test),
            "old_guard": source.count(OLD_GUARD),
        }
        if (descendant_counts["new_guard"] != 1 or descendant_counts["helper"] != 1
                or descendant_counts["untyped_test"] + descendant_counts["typed_rng_test"] != 1
                or descendant_counts["old_guard"] != 0):
            raise ValueError(
                "Rust early-target port partially applied: "
                + ", ".join(f"{key}={value}" for key, value in descendant_counts.items())
            )
        return source
    if (source.count(OLD_GUARD) != 1 or source.count(METHOD_MARKER) != 1
            or source.count(TEST_ANCHOR) != 1 or TEST_MARKER in source
            or HELPER in source):
        raise ValueError("Rust early-world-target source anchors missing or ambiguous")
    # The production method delegates only the clock predicate. The existing
    # source-native world ACK guard remains mandatory after this check.
    source = source.replace(OLD_GUARD, NEW_GUARD, 1)
    source = source.replace(METHOD_MARKER, HELPER + METHOD_MARKER, 1)
    # Insert immediately before the already compiled persistent-actor test.
    anchor = "    #[test]\n" + TEST_ANCHOR
    if source.count(anchor) != 1:
        raise ValueError("Rust native persistent regression anchor missing")
    return source.replace(anchor, TEST + anchor, 1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_early_retarget.py RUST_ENGINE_ROOT")
    path = Path(argv[1]) / "src/core/fight.rs"
    before = path.read_text()
    after = port_source(before)
    if before != after:
        path.write_text(after)
    print("RUST_NATIVE_EARLY_LETHAL_RETARGET_PORTED" if before != after
          else "RUST_NATIVE_EARLY_LETHAL_RETARGET_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
