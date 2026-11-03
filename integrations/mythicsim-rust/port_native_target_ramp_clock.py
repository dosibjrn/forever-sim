#!/usr/bin/env python3
"""Port the source-Rust next-target armor-ramp clock correction.

A new target begins at a nonzero global native clock. Its source-defined
Sunder/Expose schedules must be relative to that clock, not iteration zero.
The original single-fight schedules remain unchanged because reset sets now=0.
"""
from __future__ import annotations

import sys
from pathlib import Path

OLD_SUNDER = "self.schedule(0, PRIORITY_DOT, Action::SunderTick(position as u8, 0));"
NEW_SUNDER = "self.schedule(self.now, PRIORITY_DOT, Action::SunderTick(position as u8, 0));"
OLD_EXPOSE = "self.schedule(delay, PRIORITY_DOT, Action::ExternalExpose(position as u8));"
NEW_EXPOSE = "self.schedule(self.now + delay, PRIORITY_DOT, Action::ExternalExpose(position as u8));"
TEST_MARKER = "fn native_persistent_next_target_offsets_target_armor_events()"

TEST = """    #[test]
    fn native_persistent_next_target_offsets_target_armor_events() {
        use super::{AuraRef, ExternalExpose, SunderRamp};
        let prepared: crate::contracts::prepared_v2::PreparedV2 = serde_json::from_str(
            include_str!(concat!(env!("CARGO_MANIFEST_DIR"),
                "/fixtures/mage/prepared-v2/balance-druid-revelation.prepared.json"))
        ).unwrap();
        // Both source-backed armor ramps previously scheduled events at t=0
        // after the first pull, so the next native scheduler could rewind.
        for with_sunder in [true, false] {
            let mut fight = crate::classes::druid::agent::DruidAgent::fight(&prepared).unwrap();
            if !fight.extra_targets_built {
                fight.build_extra_targets();
                fight.build_exclusive_tracking();
                fight.apply_enemy_slow_priorities();
            }
            fight.prepare_first_native_pull();
            let mut steps = 0;
            while fight.step() {
                steps += 1;
                assert!(steps < 100_000, "first native pull did not terminate");
            }
            let at = fight.end_of_combat;
            assert!(at > 1_000_000_000);
            let aura = AuraRef { side: Side::Target, index: 0 };
            if with_sunder {
                fight.sunder = Some(SunderRamp {
                    aura, period: 2_000_000_000, ticks: 1,
                    armor_by_stacks: vec![0.0], blocked: false,
                });
            } else {
                fight.external_expose = Some(ExternalExpose {
                    aura, delay: 1_000_000_000, armor_before: 0.0,
                });
            }
            fight.begin_next_target(at, at + 3_000_000_000).unwrap();
            assert!(fight.queue.peek_time().unwrap() >= at,
                "second target queued source armor event before its own spawn");
        }
    }

"""


def port(source: str) -> str:
    if TEST_MARKER in source:
        if (source.count(TEST_MARKER) != 1
                or NEW_SUNDER not in source or NEW_EXPOSE not in source
                or OLD_SUNDER in source or OLD_EXPOSE in source):
            raise ValueError("partial or ambiguous native target-ramp port")
        return source
    for old, new in ((OLD_SUNDER, NEW_SUNDER), (OLD_EXPOSE, NEW_EXPOSE)):
        if source.count(old) != 1 or new in source:
            raise ValueError(f"missing or ambiguous native Rust source anchor: {old}")
        source = source.replace(old, new, 1)
    anchor = "mod tests {\n    use super::{Mp5Path, Side, DEFENDERS, MAX_TARGETS};\n"
    if source.count(anchor) != 1:
        raise ValueError("native Rust test module anchor missing")
    return source.replace(anchor, anchor + "\n" + TEST, 1)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_target_ramp_clock.py RUST_ENGINE_ROOT")
    path = Path(argv[1]) / "src/core/fight.rs"
    before = path.read_text()
    after = port(before)
    if after != before:
        path.write_text(after)
    print("RUST_NATIVE_TARGET_RAMP_CLOCK_PORTED" if after != before else
          "RUST_NATIVE_TARGET_RAMP_CLOCK_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
