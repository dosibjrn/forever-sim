#!/usr/bin/env python3
"""Port a real two-distinct-world-target same-actor entry point into source Rust.

The existing Rust combat scheduler and world ACK bridge remain authoritative.
No Python combat model or synthetic damage is introduced by this source port.
"""
from __future__ import annotations

import sys
from pathlib import Path

FIGHT_ANCHOR = "    /// Callable two-window source-Rust continuation smoke, NOT a 100-mob/2D gate."
CLASSES_ANCHOR = "/// Run the same native actor through two source-backed combat windows."
PREPARED_ANCHOR = "/// A real native two-window same-actor smoke; no world ACK, mob kills or paid recovery."
CLI_ANCHOR = '    if args[0] == "native-pulls" {'
METHOD_MARKER = "pub(crate) fn native_two_world_targets(&mut self)"
CLASS_MARKER = "pub(crate) fn native_two_world_targets("
PREPARED_MARKER = "pub fn native_two_world_targets("
CLI_MARKER = '    if args[0] == "native-world-pulls" {'


def insert(source: str, anchor: str, marker: str, replacement: str) -> str:
    if marker in source:
        if source.count(marker) != 1 or source.count(anchor) != 1:
            raise ValueError(f"RUST_WORLD_TWO_TARGET_PARTIAL_{marker}")
        return source
    if source.count(anchor) != 1:
        raise ValueError(f"RUST_WORLD_TWO_TARGET_ANCHOR_{anchor}")
    return source.replace(anchor, replacement + anchor, 1)


FIGHT_METHOD = """    /// Two genuinely distinct gsim world mobs, one selected source-Rust actor.
    /// Both must die from native damage with a committed world HP/hash ACK.
    /// No paid recovery is simulated; this is not P4-P6 certification.
    pub(crate) fn native_two_world_targets(&mut self)
        -> Result<serde_json::Value, &'static str>
    {
        if !world_bridge::enabled() {
            return Err("RUST_TWO_WORLD_TARGETS_REQUIRES_GSIM");
        }
        if !self.extra_targets_built {
            self.build_extra_targets();
            self.build_exclusive_tracking();
            self.apply_enemy_slow_priorities();
        }
        self.rng.reseed(self.config.seed as u64);
        self.log = None;
        world_bridge::begin_iteration(0);
        self.prepare_first_native_pull();
        while self.step() {}
        if !world_bridge::acknowledged_lethal() {
            return Err("RUST_FIRST_WORLD_TARGET_NOT_NATIVE_LETHAL");
        }
        let first_clock = self.now;
        let first_damage = self.encounter_damage_taken;
        let first = serde_json::json!({
            "index": 0, "native_kill_ns": first_clock,
            "native_damage": first_damage,
            "actor_mana": self.player.mana, "actor_health": self.player.health,
        });
        // The next gsim boundary is one representable millisecond after the
        // acknowledged kill; no fabricated free travel or resource reset.
        let next_at = first_clock.checked_add(1_000_000)
            .ok_or("RUST_WORLD_TARGET_CLOCK_OVERFLOW")?;
        let next_end = next_at.checked_add(self.config.base_duration)
            .ok_or("RUST_WORLD_TARGET_DURATION_OVERFLOW")?;
        self.begin_next_target(next_at, next_end)?;
        while self.step() {}
        if !world_bridge::acknowledged_lethal() {
            return Err("RUST_SECOND_WORLD_TARGET_NOT_NATIVE_LETHAL");
        }
        let second = serde_json::json!({
            "index": 1, "native_kill_ns": self.now,
            "native_damage": self.encounter_damage_taken - first_damage,
            "actor_mana": self.player.mana, "actor_health": self.player.health,
        });
        let report = serde_json::json!({
            "scope": "TWO_REAL_GSIM_2D_KILLS_SAME_NATIVE_ACTOR_NOT_P4_P6",
            "continuous_native_actor": true, "actual_2d_ack": true,
            "paid_recovery": false, "world_targets_killed": 2,
            "windows": [first, second],
        });
        self.cleanup();
        Ok(report)
    }

"""

CLASS_METHOD = """/// Two source-native kills with real gsim world HP/hash ACK and one actor.
pub(crate) fn native_two_world_targets(
    prepared: &crate::contracts::prepared_v2::PreparedV2,
) -> Result<serde_json::Value, String> {
    match prepared.player.class.as_str() {
        "ClassMage" => mage::agent::MageAgent::fight(prepared)?.native_two_world_targets().map_err(str::to_string),
        "ClassDruid" => druid::agent::DruidAgent::fight(prepared)?.native_two_world_targets().map_err(str::to_string),
        "ClassWarlock" => warlock::agent::WarlockAgent::fight(prepared)?.native_two_world_targets().map_err(str::to_string),
        "ClassShaman" => shaman::agent::ShamanAgent::fight(prepared)?.native_two_world_targets().map_err(str::to_string),
        "ClassPaladin" => paladin::agent::PaladinAgent::fight(prepared)?.native_two_world_targets().map_err(str::to_string),
        "ClassPriest" => priest::agent::PriestAgent::fight(prepared)?.native_two_world_targets().map_err(str::to_string),
        "ClassRogue" => rogue::agent::RogueAgent::fight(prepared)?.native_two_world_targets().map_err(str::to_string),
        "ClassWarrior" => warrior::agent::WarriorAgent::fight(prepared)?.native_two_world_targets().map_err(str::to_string),
        "ClassHunter" => hunter::agent::HunterAgent::fight(prepared)?.native_two_world_targets().map_err(str::to_string),
        other => Err(format!("class {other} has no native fight agent")),
    }
}

"""

PREPARED_METHOD = """/// Same selected native actor across two real world-lethal ACKs, not a gate.
pub fn native_two_world_targets(prepared: &PreparedV2)
    -> Result<serde_json::Value, PreparedError>
{
    check(prepared)?;
    if !crate::core::fight::world_bridge::enabled() {
        return Err(PreparedError::Invalid(
            "RUST_TWO_WORLD_TARGETS_REQUIRES_GSIM".to_owned()));
    }
    crate::core::fight::world_bridge::start(&prepared.request_sha256);
    crate::classes::native_two_world_targets(prepared).map_err(PreparedError::Invalid)
}

"""

CLI_METHOD = """    if args[0] == "native-world-pulls" {
        if args.len() != 5 || args[1] != "--infile"
            || args[3] != "--targets" || args[4] != "2" {
            return Err("native-world-pulls requires --infile PREPARED_V2.json --targets 2".into());
        }
        let input = fs::read(&args[2]).map_err(|err| err.to_string())?;
        let prepared = prepared_v2(&input)?
            .ok_or("native-world-pulls requires a prepared v2 input")?;
        let report = native_two_world_targets(&prepared).map_err(|err| err.to_string())?;
        println!("{}", serde_json::json!({
            "engine": "forever-engine",
            "source_sha256": prepared.request_sha256,
            "result": report, "checkpoint_certified": false,
        }));
        return Ok(());
    }
"""


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_two_world_cli.py RUST_ENGINE_ROOT")
    root = Path(argv[1]) / "src"
    edits = [
        (root / "core/fight.rs", lambda s: insert(s, FIGHT_ANCHOR, METHOD_MARKER, FIGHT_METHOD)),
        (root / "classes.rs", lambda s: insert(s, CLASSES_ANCHOR, CLASS_MARKER, CLASS_METHOD)),
        (root / "engine/prepared.rs",
         lambda s: insert(s, PREPARED_ANCHOR, PREPARED_MARKER, PREPARED_METHOD)),
        (root / "lib.rs", lambda s: insert(
            s, "    native_two_pull_windows,", "    native_two_world_targets,",
            "    native_two_world_targets,\n")),
        (root / "main.rs", lambda s: insert(
            insert(s, CLI_ANCHOR, CLI_MARKER, CLI_METHOD),
            "contracts::prepared_v2::PreparedV2, native_two_pull_windows,",
            "contracts::prepared_v2::PreparedV2, native_two_pull_windows, native_two_world_targets,",
            "")),
    ]
    # The import edit in main.rs is a substitution, not a new statement.
    edits[-1] = (root / "main.rs", lambda s: insert(
        s.replace(
            "contracts::prepared_v2::PreparedV2, native_two_pull_windows,",
            "contracts::prepared_v2::PreparedV2, native_two_pull_windows, native_two_world_targets,",
            1) if "native_two_world_targets," not in s else s,
        CLI_ANCHOR, CLI_MARKER, CLI_METHOD))
    for path, port in edits:
        before = path.read_text()
        after = port(before)
        if before != after:
            path.write_text(after)
    print("RUST_NATIVE_TWO_DISTINCT_WORLD_TARGET_CLI_PORTED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
