#!/usr/bin/env python3
"""Port a callable two-window native actor probe into the selected Rust engine.

This runs real selected Rust combat on one actor across two target boundaries.
It does NOT claim dead targets, paid recovery, actual 2D coupling or P4–P6 PASS.
The existing native two-target source primitive remains the authority.
"""
from __future__ import annotations

import sys
from pathlib import Path

FIGHT_MARKER = "    pub(crate) fn native_two_pull_windows(&mut self)"
PREPARE_MARKER = "    fn prepare_first_native_pull(&mut self) {"
CLI_MARKER = '    if args[0] == "native-pulls" {'
ENGINE_MARKER = "pub fn native_two_pull_windows(prepared: &PreparedV2)"
ENGINE_TYPED_MARKER = ENGINE_MARKER.replace(
    "prepared: &PreparedV2)",
    "prepared: &PreparedV2, rng_mode: crate::core::rng::RngMode)",
)
ENGINE_CALL_OLD = "crate::classes::native_two_pull_windows(prepared).map_err(PreparedError::Invalid)"
ENGINE_TYPED_CALL = "crate::classes::native_two_pull_windows(prepared, rng_mode).map_err(PreparedError::Invalid)"
ENGINE_TYPED_MARKER = ENGINE_MARKER.replace(
    "prepared: &PreparedV2)",
    "prepared: &PreparedV2, rng_mode: crate::core::rng::RngMode)",
)
ENGINE_CALL_OLD = "crate::classes::native_two_pull_windows(prepared).map_err(PreparedError::Invalid)"
ENGINE_TYPED_CALL = "crate::classes::native_two_pull_windows(prepared, rng_mode).map_err(PreparedError::Invalid)"


def replace_once(source: str, old: str, new: str, name: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"{name}: source anchor missing or ambiguous")
    return source.replace(old, new, 1)


def port_fight(source: str) -> str:
    if FIGHT_MARKER in source:
        if source.count(FIGHT_MARKER) != 1 or source.count(PREPARE_MARKER) != 1:
            raise ValueError("native two-pull source partially/ambiguously installed")
        return source
    header = "    fn run_once(&mut self) {\n"
    cutoff = "        while self.step() {}\n"
    if source.count(header) != 1:
        raise ValueError("run_once anchor missing")
    before, tail = source.split(header, 1)
    if tail.count(cutoff) < 1:
        raise ValueError("run_once stepping anchor missing")
    setup, rest = tail.split(cutoff, 1)
    if not setup.startswith("        self.reset();\n"):
        raise ValueError("run_once first-pull reset changed")
    if PREPARE_MARKER in source:
        raise ValueError("unexpected preexisting native first-pull helper")
    # Share exactly the original native reset/prepull scheduling code.
    # The existing one-shot simulator must behave identically.
    shared = PREPARE_MARKER + "\n" + setup + "    }\n\n"
    new_once = (header + "        self.prepare_first_native_pull();\n" + cutoff)
    source = before + shared + new_once + rest
    marker = "    /// Begin a second distinct world target on the SAME native actor.\n"
    method = '''    /// Callable two-window source-Rust continuation smoke, NOT a 100-mob/2D gate.
    /// Both windows use real native scheduler actions and the same player/queue.
    /// This diagnostic is duration-bounded; no mob death or paid downtime is claimed.
    pub(crate) fn native_two_pull_windows(&mut self)
        -> Result<serde_json::Value, &'static str>
    {
        if world_bridge::enabled() {
            return Err("RUST_TWO_WINDOW_2D_CONTROLLER_NOT_CONNECTED");
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
        let first_end_ns = self.end_of_combat;
        let first = serde_json::json!({
            "index": 0, "end_ns": first_end_ns,
            "actor_mana": self.player.mana, "actor_health": self.player.health,
        });
        let second_end_ns = first_end_ns.checked_add(self.config.base_duration)
            .ok_or("RUST_TWO_WINDOW_DURATION_OVERFLOW")?;
        self.begin_next_target(first_end_ns, second_end_ns)?;
        while self.step() {}
        let second = serde_json::json!({
            "index": 1, "end_ns": self.end_of_combat,
            "actor_mana": self.player.mana, "actor_health": self.player.health,
        });
        let report = serde_json::json!({
            "scope": "NATIVE_TWO_DURATION_WINDOWS_DIAGNOSTIC_NOT_GATE",
            "selected_native_combat": true,
            "actual_2d_ack": false, "paid_recovery": false,
            "continuous_actor": true, "windows": [first, second],
        });
        self.cleanup();
        Ok(report)
    }

'''
    source = replace_once(source, marker, method + marker, "native method")
    return source


def port_classes(source: str) -> str:
    marker = "/// The class agent Rust preparation builds for a player:"
    function_marker = "pub(crate) fn native_two_pull_windows("
    if function_marker in source:
        if source.count(function_marker) != 1:
            raise ValueError("ambiguous class native two-pull dispatcher")
        start = source.index(function_marker)
        end = source.find("\npub(crate) fn ", start + len(function_marker))
        block = source[start:end] if end >= 0 else source[start:]
        if ("rng_mode: crate::core::rng::RngMode" not in block
                or block.count("::fight(prepared, rng_mode)?") != 9
                or block.count(".native_two_pull_windows().map_err(str::to_string)") != 9):
            raise ValueError("native two-pull class dispatcher lacks typed RNG")
        return source
    pairs = (
        ("Mage", "mage", "Mage"), ("Druid", "druid", "Druid"),
        ("Warlock", "warlock", "Warlock"), ("Shaman", "shaman", "Shaman"),
        ("Paladin", "paladin", "Paladin"), ("Priest", "priest", "Priest"),
        ("Rogue", "rogue", "Rogue"), ("Warrior", "warrior", "Warrior"),
        ("Hunter", "hunter", "Hunter"),
    )
    cases = "\n".join(
        f'        "Class{key}" => {module}::agent::{agent}Agent::fight(prepared, rng_mode)?.native_two_pull_windows().map_err(str::to_string),'
        for key, module, agent in pairs
    )
    method = (
        "/// Run the same native actor through two source-backed combat windows.\n"
        "/// This is a bounded diagnostic, not a live-2D or leveling gate.\n"
        "pub(crate) fn native_two_pull_windows(\n"
        "    prepared: &crate::contracts::prepared_v2::PreparedV2,\n"
        "    rng_mode: crate::core::rng::RngMode,\n"
        ") -> Result<serde_json::Value, String> {\n"
        "    match prepared.player.class.as_str() {\n" + cases + "\n"
        '        other => Err(format!("class {other} has no native fight agent")),\n'
        "    }\n}\n\n"
    )
    return replace_once(source, marker, method + marker, "typed class dispatcher")

def port_prepared(source: str) -> str:
    if ENGINE_TYPED_MARKER in source:
        if (source.count(ENGINE_TYPED_MARKER) != 1
                or source.count(ENGINE_TYPED_CALL) != 1
                or ENGINE_MARKER in source
                or ENGINE_CALL_OLD in source):
            raise ValueError("typed prepared two-pull gateway drift")
        return source
    if ENGINE_MARKER in source:
        if source.count(ENGINE_MARKER) != 1 or source.count(ENGINE_CALL_OLD) != 1:
            raise ValueError("untyped prepared two-pull gateway partial")
        source = source.replace(ENGINE_MARKER, ENGINE_TYPED_MARKER, 1)
        return source.replace(ENGINE_CALL_OLD, ENGINE_TYPED_CALL, 1)
    marker = "/// What gating a prepared v2 input and simulating it when supported came to."
    code = '''/// A real native two-window same-actor smoke; no world ACK, mob kills or paid recovery.
pub fn native_two_pull_windows(prepared: &PreparedV2, rng_mode: crate::core::rng::RngMode)
    -> Result<serde_json::Value, PreparedError>
{
    check(prepared)?;
    crate::classes::native_two_pull_windows(prepared, rng_mode).map_err(PreparedError::Invalid)
}

'''
    return replace_once(source, marker, code + marker, "typed prepared gateway")

def port_lib(source: str) -> str:
    marker = "    check as check_prepared, coverage as prepared_coverage, refusals as prepared_refusals,"
    if "native_two_pull_windows" in source:
        if source.count("native_two_pull_windows") != 1:
            raise ValueError("ambiguous lib export")
        return source
    return replace_once(source, marker, marker + "\n    native_two_pull_windows,", "lib export")


def port_main(source: str) -> str:
    if CLI_MARKER in source:
        if source.count(CLI_MARKER) != 1:
            raise ValueError("ambiguous native-pulls CLI")
        block = source[source.index(CLI_MARKER):]
        if ('args[5] != "--rng-mode"' not in block
                or "RngMode::parse_cli(&args[6])?" not in block
                or "native_two_pull_windows(&prepared, mode)" not in block):
            raise ValueError("native-pulls CLI lacks explicit typed RNG mode")
        return source
    source = replace_once(
        source,
        "    contracts::prepared_v2::PreparedV2, prepare_json_with, prepared_refusals, simulate,",
        "    contracts::prepared_v2::PreparedV2, native_two_pull_windows, prepare_json_with, prepared_refusals, simulate,",
        "main import",
    )
    help_marker = '    if args.len() == 3 && args[0] == "check" && args[1] == "--infile" {\n'
    code = '''    if args[0] == "native-pulls" {
        if args.len() != 7 || args[1] != "--infile"
            || args[3] != "--targets" || args[4] != "2"
            || args[5] != "--rng-mode" {
            return Err("native-pulls requires --infile PREPARED_V2.json --targets 2 --rng-mode balanced|stochastic".into());
        }
        let mode = RngMode::parse_cli(&args[6])?;
        let input = fs::read(&args[2]).map_err(|err| err.to_string())?;
        let prepared = prepared_v2(&input)?
            .ok_or("native-pulls requires a prepared v2 input")?;
        let windows = native_two_pull_windows(&prepared, mode).map_err(|err| err.to_string())?;
        println!("{}", serde_json::json!({
            "engine": "forever-engine",
            "source_sha256": prepared.request_sha256,
            "scenario_id": prepared.scenario_id,
            "result": windows,
            "checkpoint_certified": false,
        }));
        return Ok(());
    }
'''
    return replace_once(source, help_marker, code + help_marker, "typed CLI command")

def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_two_pull_cli.py RUST_ENGINE_ROOT")
    root = Path(argv[1])
    edits = (
        ("src/core/fight.rs", port_fight),
        ("src/classes.rs", port_classes),
        ("src/engine/prepared.rs", port_prepared),
        ("src/lib.rs", port_lib),
        ("src/main.rs", port_main),
    )
    changed = 0
    for path, patch in edits:
        file = root / path
        before = file.read_text()
        after = patch(before)
        if before != after:
            file.write_text(after)
            changed += 1
    print("RUST_NATIVE_TWO_WINDOW_CLI_PORTED" if changed else
          "RUST_NATIVE_TWO_WINDOW_CLI_ALREADY_PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
