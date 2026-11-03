#!/usr/bin/env python3
"""Expose source-Rust player health damage in each retained world-target window.

Read the already-paid canonical Rust damage_taken_health resource. This is
not a new damage rule, recovered health, or an incoming-attack fixture.
"""
from pathlib import Path
import sys

METHOD = "pub(crate) fn native_two_world_targets(&mut self, target_count: usize)"
END = "        let report = serde_json::json!({"
INITIAL = "        let mut previous_damage = 0.0;"
HEALTH = '                "actor_health": self.player.health,'
UPDATE = "            previous_damage = total_damage;"
MARKER = '"native_health_damage_taken"'
SETUP = """        let mut previous_health_damage = 0.0_f64;
        let mut previous_health_damage_events = 0;
"""
BEFORE_WINDOW = """            // Only native Rust owns player damage and its resource metrics.
            // Health may regenerate between attacks; remaining HP is not damage taken.
            let health_damage = -self.resources[self.damage_taken_health].gain;
            let health_damage_events = self.resources[self.damage_taken_health].events;
            if health_damage < previous_health_damage
                || health_damage_events < previous_health_damage_events
            {
                return Err("RUST_WORLD_HEALTH_DAMAGE_RECEIPT_NONMONOTONIC");
            }
"""
FIELDS = """                "native_health_damage_taken": health_damage - previous_health_damage,
                "native_health_damage_events": health_damage_events - previous_health_damage_events,
"""
AFTER_WINDOW = """            previous_health_damage = health_damage;
            previous_health_damage_events = health_damage_events;
"""


def port(source: str) -> str:
    if source.count(METHOD) != 1:
        from port_native_paid_recovery import (
            FIGHT_SIGNATURE_NEW, is_composed_paid_recovery_source,
        )
        if FIGHT_SIGNATURE_NEW in source and is_composed_paid_recovery_source(source):
            return source
        raise ValueError("RUST_NATIVE_HEALTH_RECEIPT_METHOD_MISSING_OR_DUPLICATE")
    start = source.index(METHOD)
    end = source.find(END, start)
    if end < 0:
        raise ValueError("RUST_NATIVE_HEALTH_RECEIPT_REPORT_ANCHOR_MISSING")
    block = source[start:end]
    if MARKER in block:
        if (block.count(MARKER) != 1
                or "previous_health_damage_events = health_damage_events;" not in block
                or block.count('"native_health_damage_events"') != 1):
            raise ValueError("RUST_NATIVE_HEALTH_RECEIPT_PARTIAL")
        return source
    for anchor in (INITIAL, HEALTH, UPDATE):
        if block.count(anchor) != 1:
            raise ValueError("RUST_NATIVE_HEALTH_RECEIPT_SOURCE_DRIFT")
    block = block.replace(INITIAL, INITIAL + "\n" + SETUP, 1)
    block = block.replace("            windows.push(serde_json::json!({",
                          BEFORE_WINDOW + "            windows.push(serde_json::json!({", 1)
    block = block.replace(HEALTH, HEALTH + "\n" + FIELDS.rstrip("\n"), 1)
    block = block.replace(UPDATE, UPDATE + "\n" + AFTER_WINDOW.rstrip("\n"), 1)
    if block.count(MARKER) != 1:
        raise ValueError("RUST_NATIVE_HEALTH_RECEIPT_INSERT_FAILED")
    return source[:start] + block + source[end:]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_health_damage_receipts.py RUST_ENGINE_ROOT")
    path = Path(argv[1]) / "src/core/fight.rs"
    before = path.read_text()
    after = port(before)
    if before != after:
        path.write_text(after)
    print("RUST_NATIVE_HEALTH_DAMAGE_RECEIPTS_PORTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
