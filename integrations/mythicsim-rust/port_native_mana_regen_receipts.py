#!/usr/bin/env python3
"""Expose actual selected-Rust mana-regeneration events per retained world target.

Read the source combat engine's existing ResourceMetrics. No Python regeneration,
synthetic idle time, paid recovery, or P4–P6 gate acceptance is implemented here.
"""
from pathlib import Path
import sys

METHOD = "pub(crate) fn native_two_world_targets(&mut self, target_count: usize)"
END = '        let report = serde_json::json!({'
INITIAL = "        let mut previous_health_damage_events = 0;"
HEALTH = '                "native_health_damage_events": health_damage_events - previous_health_damage_events,'
UPDATE = "            previous_health_damage_events = health_damage_events;"
MARKER = '"native_combat_mana_regen_actual_gain"'

SETUP = """        let mut previous_mana_regen_gain = 0.0_f64;
        let mut previous_mana_regen_events = 0_i32;
"""
BEFORE_WINDOW = """            // Existing source-native 2-second mana ticks own these gains.
            // These events include in-combat ticks, NOT paid between-pull rest.
            let mana_regen_gain = self.resources[self.mana_regen_casting].actual_gain
                + self.resources[self.mana_regen_not_casting].actual_gain;
            let mana_regen_events = self.resources[self.mana_regen_casting].events
                + self.resources[self.mana_regen_not_casting].events;
            if !mana_regen_gain.is_finite()
                || mana_regen_gain < previous_mana_regen_gain - 1e-8
                || mana_regen_events < previous_mana_regen_events
            {
                return Err("RUST_WORLD_MANA_REGEN_RECEIPT_NONMONOTONIC");
            }
"""
FIELDS = """                "native_combat_mana_regen_actual_gain":
                    (mana_regen_gain - previous_mana_regen_gain).max(0.0),
                "native_combat_mana_regen_events":
                    mana_regen_events - previous_mana_regen_events,
"""
AFTER_WINDOW = """            previous_mana_regen_gain = mana_regen_gain;
            previous_mana_regen_events = mana_regen_events;
"""


def port(source: str) -> str:
    if source.count(METHOD) != 1:
        from port_native_paid_recovery import (
            FIGHT_SIGNATURE_NEW, is_composed_paid_recovery_source,
        )
        if FIGHT_SIGNATURE_NEW in source and is_composed_paid_recovery_source(source):
            return source
        raise ValueError("RUST_MANA_REGEN_METHOD_MISSING_OR_DUPLICATE")
    start = source.index(METHOD)
    end = source.find(END, start)
    if end < 0:
        raise ValueError("RUST_MANA_REGEN_REPORT_ANCHOR_MISSING")
    block = source[start:end]
    if MARKER in block:
        if (block.count(MARKER) != 1
                or block.count('"native_combat_mana_regen_events"') != 1
                or block.count(AFTER_WINDOW.strip()) != 1
                or block.count(BEFORE_WINDOW.strip()) != 1):
            raise ValueError("RUST_MANA_REGEN_RECEIPT_PARTIAL")
        return source
    for anchor in (INITIAL, HEALTH, UPDATE, "            windows.push(serde_json::json!({"):
        if block.count(anchor) != 1:
            raise ValueError("RUST_MANA_REGEN_SOURCE_DRIFT")
    block = block.replace(INITIAL, INITIAL + "\n" + SETUP.rstrip("\n"), 1)
    block = block.replace("            windows.push(serde_json::json!({",
                          BEFORE_WINDOW + "            windows.push(serde_json::json!({", 1)
    block = block.replace(HEALTH, HEALTH + "\n" + FIELDS.rstrip("\n"), 1)
    block = block.replace(UPDATE, UPDATE + "\n" + AFTER_WINDOW.rstrip("\n"), 1)
    if block.count(MARKER) != 1:
        raise ValueError("RUST_MANA_REGEN_INSERT_FAILED")
    return source[:start] + block + source[end:]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_mana_regen_receipts.py RUST_ENGINE_ROOT")
    path = Path(argv[1]) / "src/core/fight.rs"
    before = path.read_text()
    after = port(before)
    if before != after:
        path.write_text(after)
    print("RUST_NATIVE_COMBAT_MANA_REGEN_RECEIPTS_PORTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
