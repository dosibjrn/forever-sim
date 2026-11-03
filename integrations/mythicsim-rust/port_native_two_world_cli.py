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
# Keep the original prepared.rs anchor: the preceding two-pull port may already
# own its diagnostic docstring, so that docstring is not a stable downstream seam.
PREPARED_ANCHOR = "/// What gating a prepared v2 input and simulating it when supported came to."
CLI_ANCHOR = '    if args[0] == "native-pulls" {'
METHOD_MARKER = "pub(crate) fn native_two_world_targets(&mut self, target_count: usize)"
CLASS_MARKER = "pub(crate) fn native_two_world_targets("
PREPARED_MARKER = "pub fn native_two_world_targets("
CLI_MARKER = '    if args[0] == "native-world-pulls" {'


# Exact previously published two-target implementation markers. A fork may
# already carry the tested #447 source before its gitlink is selected on main.
# Upgrade that source in place; never add duplicate Rust functions/CLI arms.
LEGACY_PORTS = {
    METHOD_MARKER: (
        "    /// Two genuinely distinct gsim world mobs, one selected source-Rust actor.",
        ("pub(crate) fn native_two_world_targets(&mut self)",
         'RUST_SECOND_WORLD_TARGET_NOT_NATIVE_LETHAL',
         'RUST_FIRST_WORLD_TARGET_NOT_NATIVE_LETHAL',
         '"world_targets_killed": 2'),
    ),
    CLASS_MARKER: (
        "/// Two source-native kills with real gsim world HP/hash ACK and one actor.",
        ("pub(crate) fn native_two_world_targets(",
         "native_two_world_targets().map_err(str::to_string)",
         '"ClassHunter"'),
    ),
    PREPARED_MARKER: (
        "/// Same selected native actor across two real world-lethal ACKs, not a gate.",
        ("pub fn native_two_world_targets(prepared: &PreparedV2)",
         "crate::classes::native_two_world_targets(prepared).map_err(PreparedError::Invalid)",
         "world_bridge::start(&prepared.request_sha256)"),
    ),
    CLI_MARKER: (
        '    if args[0] == "native-world-pulls" {',
        ('args[4] != "2"',
         'native_two_world_targets(&prepared)',
         '"checkpoint_certified": false'),
    ),
}


def typed_rng_variant(marker: str, replacement: str) -> str:
    """Exact published typed-RNG descendant of the original multi-world port."""
    rng = "crate::core::rng::RngMode"
    if marker == CLASS_MARKER:
        return (replacement.replace(
            "    target_count: usize,\n", "    target_count: usize,\n    rng_mode: " + rng + ",\n", 1)
            .replace("::fight(prepared)?", "::fight(prepared, rng_mode)?"))
    if marker == PREPARED_MARKER:
        return (replacement.replace(
            "target_count: usize)", "target_count: usize, rng_mode: " + rng + ")", 1)
            .replace("native_two_world_targets(prepared, target_count)",
                     "native_two_world_targets(prepared, target_count, rng_mode)", 1))
    if marker == CLI_MARKER:
        return (replacement.replace(
            'args.len() != 5 || args[1] != "--infile" || args[3] != "--targets"',
            'args.len() != 7 || args[1] != "--infile" || args[3] != "--targets" || args[5] != "--rng-mode"', 1)
            .replace("let report = native_two_world_targets(&prepared, target_count)",
                     "let mode = RngMode::parse_cli(&args[6])?;\n        let report = native_two_world_targets(&prepared, target_count, mode)", 1))
    raise ValueError("RUST_WORLD_TYPED_RNG_VARIANT_UNSUPPORTED")



def _typed_native_world_present(source: str, marker: str) -> bool:
    if marker not in source:
        return False
    start = source.index(marker)
    if marker == CLASS_MARKER:
        end = source.find("\n/// Run the same native actor through two source-backed combat windows.", start)
        block = source[start:end] if end >= 0 else source[start:]
        common = (
            "rng_mode: crate::core::rng::RngMode" in block
            and block.count("::fight(prepared, rng_mode)?") == 9
        )
        if "recovery_ns" in block:
            return (
                common
                and "recovery_ns: i64" in block
                and block.count(".native_two_world_targets(target_count, recovery_ns)") == 9
            )
        return common and block.count(".native_two_world_targets(target_count)") == 9
    if marker == PREPARED_MARKER:
        end = source.find("\n" + PREPARED_ANCHOR, start)
        block = source[start:end] if end >= 0 else source[start:]
        common = "rng_mode: crate::core::rng::RngMode" in block
        if "recovery_ns" in block:
            return (
                common
                and "recovery_ns: i64" in block
                and "crate::classes::native_two_world_targets(prepared, target_count, rng_mode, recovery_ns)" in block
            )
        return (
            common
            and "crate::classes::native_two_world_targets(prepared, target_count, rng_mode)" in block
        )
    if marker == CLI_MARKER:
        end = source.find('    if args[0] == "native-pulls" {', start)
        block = source[start:end] if end >= 0 else source[start:]
        common = (
            'args[5] != "--rng-mode"' in block
            and "RngMode::parse_cli(&args[6])?" in block
        )
        if "recovery_ns" in block or "--recovery-ns" in block:
            return (
                common
                and "if !matches!(args.len(), 7 | 9)" in block
                and 'args[7] != "--recovery-ns"' in block
                and "args[8].parse::<i64>()" in block
                and "native_two_world_targets(&prepared, target_count, mode, recovery_ns)" in block
            )
        return (
            common
            and "args.len() != 7" in block
            and "native_two_world_targets(&prepared, target_count, mode)" in block
        )
    return False


def insert(source: str, anchor: str, marker: str, replacement: str) -> str:
    if source.count(anchor) != 1:
        raise ValueError(f"RUST_WORLD_MULTI_TARGET_ANCHOR_{anchor}")
    # The published selected Rust fork already has typed RNG. Its complete
    # source method and the subsequent paid-recovery descendant are valid
    # idempotent outcomes; a partial signature/call-site change is not.
    if marker in (CLASS_MARKER, PREPARED_MARKER, CLI_MARKER):
        typed = typed_rng_variant(marker, replacement)
        # Use the structural validator as the only idempotence fast path.
        # Substring containment is unsafe: a typed base fragment can also be
        # present inside a malformed paid-recovery descendant.
        if _typed_native_world_present(source, marker):
            return source
        from port_native_paid_recovery import port_classes, port_prepared, port_main
        transform = {
            CLASS_MARKER: port_classes,
            PREPARED_MARKER: port_prepared,
            CLI_MARKER: port_main,
        }[marker]
        try:
            paid_typed = transform(typed)
            if source.count(paid_typed) == 1 and transform(source) == source:
                return source
        except ValueError:
            pass
    # Paid recovery extends every layer of the two-world API. Recognize each
    # exact downstream signature before the base CLI port checks its old
    # replacement, otherwise the second source-port pass mistakes the valid
    # recovery extension for a partial method.
    if marker == CLASS_MARKER:
        from port_native_paid_recovery import CLASSES_SIGNATURE_NEW, port_classes
        if CLASSES_SIGNATURE_NEW in source:
            if port_classes(source) == source:
                return source
            raise ValueError("RUST_WORLD_MULTI_TARGET_PAID_RECOVERY_CLASSES_DRIFT")
    if marker == PREPARED_MARKER:
        from port_native_paid_recovery import PREPARED_SIGNATURE_NEW, port_prepared
        if PREPARED_SIGNATURE_NEW in source:
            if port_prepared(source) == source:
                return source
            raise ValueError("RUST_WORLD_MULTI_TARGET_PAID_RECOVERY_PREPARED_DRIFT")
    if marker == CLI_MARKER:
        from port_native_paid_recovery import CLI_NEW, port_main
        if CLI_NEW in source:
            if port_main(source) == source:
                return source
            raise ValueError("RUST_WORLD_MULTI_TARGET_PAID_RECOVERY_CLI_DRIFT")
    if marker == METHOD_MARKER:
        from port_native_paid_recovery import (
            FIGHT_SIGNATURE_NEW, is_composed_paid_recovery_source,
        )
        if FIGHT_SIGNATURE_NEW in source:
            if is_composed_paid_recovery_source(source):
                return source
            raise ValueError("RUST_WORLD_MULTI_TARGET_PAID_RECOVERY_DESCENDANT_DRIFT")
    # Paid recovery changes the class/prepared/CLI signatures as well as the
    # fight method. Reapplying the original source port must recognize only
    # the exact composed descendant, never add duplicate entry points.
    if marker in (CLASS_MARKER, PREPARED_MARKER, CLI_MARKER):
        from port_native_paid_recovery import port_classes, port_prepared, port_main
        transform = {
            CLASS_MARKER: port_classes,
            PREPARED_MARKER: port_prepared,
            CLI_MARKER: port_main,
        }[marker]
        try:
            expected = transform(replacement)
            if source.count(expected) == 1 and transform(source) == source:
                return source
        except ValueError:
            pass
    if source.count(replacement) == 1:
        return source
    # The maintained two-world method may already have separately
    # source-validated native health-damage and mana-regeneration receipts.
    # Preserve those exact composable extensions on repeated source-port runs;
    # do not accept drift in either downstream extension.
    if marker == METHOD_MARKER:
        expected = replacement
        if '"native_health_damage_taken"' in source:
            from port_native_health_damage_receipts import port as port_health
            expected = port_health(expected)
        if '"native_combat_mana_regen_actual_gain"' in source:
            from port_native_mana_regen_receipts import port as port_mana
            expected = port_mana(expected)
        if source.count(expected) == 1:
            return source
    if source.count(replacement) > 1:
        raise ValueError(f"RUST_WORLD_MULTI_TARGET_DUPLICATE_{marker}")
    # The previously validated two-target CLI and methods already exist in the
    # maintained public Rust fork on some source lineages. Replace only their
    # exact identified bounded block, never another function or game mechanic.
    if marker in LEGACY_PORTS:
        beginning, required = LEGACY_PORTS[marker]
        if beginning in source:
            if source.count(beginning) != 1:
                raise ValueError(f"RUST_WORLD_MULTI_TARGET_LEGACY_AMBIGUOUS_{marker}")
            start = source.index(beginning)
            end = source.index(anchor)
            older = source[start:end]
            if start >= end or any(token not in older for token in required):
                raise ValueError(f"RUST_WORLD_MULTI_TARGET_LEGACY_DRIFT_{marker}")
            return source[:start] + replacement + source[end:]
    if marker in source:
        raise ValueError(f"RUST_WORLD_MULTI_TARGET_PARTIAL_{marker}")
    return source.replace(anchor, replacement + anchor, 1)


FIGHT_METHOD = """
    /// Multiple distinct gsim world deaths on one retained source-Rust actor.
    /// This diagnostic does NOT charge movement/recovery or certify P4–P6.
    pub(crate) fn native_two_world_targets(&mut self, target_count: usize)
        -> Result<serde_json::Value, &'static str>
    {
        if !world_bridge::enabled() {
            return Err("RUST_MULTI_WORLD_TARGETS_REQUIRES_GSIM");
        }
        if !(2..=100).contains(&target_count) {
            return Err("RUST_MULTI_WORLD_TARGET_COUNT_INVALID");
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
        let mut windows = Vec::with_capacity(target_count);
        let mut previous_damage = 0.0;
        for index in 0..target_count {
            if index != 0 {
                // No free actor reset. This intentionally retains the current
                // no-downtime diagnostic clock until real paid travel/recovery
                // is coupled through the same native/world timeline.
                let next_at = self.now.checked_add(1_000_000)
                    .ok_or("RUST_WORLD_TARGET_CLOCK_OVERFLOW")?;
                let next_end = next_at.checked_add(self.config.base_duration)
                    .ok_or("RUST_WORLD_TARGET_DURATION_OVERFLOW")?;
                self.begin_next_target(next_at, next_end)?;
            }
            while self.step() {}
            if !world_bridge::acknowledged_lethal() {
                return Err("RUST_MULTI_WORLD_TARGET_NOT_NATIVE_LETHAL");
            }
            let total_damage = self.encounter_damage_taken;
            windows.push(serde_json::json!({
                "index": index,
                "native_kill_ns": self.now,
                "native_damage": total_damage - previous_damage,
                "actor_mana": self.player.mana,
                "actor_health": self.player.health,
            }));
            previous_damage = total_damage;
        }
        let report = serde_json::json!({
            "scope": "MULTI_GSIM_2D_KILLS_SAME_NATIVE_ACTOR_NOT_P4_P6",
            "continuous_native_actor": true, "actual_2d_ack": true,
            "paid_recovery": false, "world_targets_killed": target_count,
            "windows": windows,
        });
        self.cleanup();
        Ok(report)
    }

"""

CLASS_METHOD = """
/// Multiple distinct world ACKs with one source-native actor.
pub(crate) fn native_two_world_targets(
    prepared: &crate::contracts::prepared_v2::PreparedV2,
    target_count: usize,
) -> Result<serde_json::Value, String> {
    match prepared.player.class.as_str() {
        "ClassMage" => mage::agent::MageAgent::fight(prepared)?.native_two_world_targets(target_count).map_err(str::to_string),
        "ClassDruid" => druid::agent::DruidAgent::fight(prepared)?.native_two_world_targets(target_count).map_err(str::to_string),
        "ClassWarlock" => warlock::agent::WarlockAgent::fight(prepared)?.native_two_world_targets(target_count).map_err(str::to_string),
        "ClassShaman" => shaman::agent::ShamanAgent::fight(prepared)?.native_two_world_targets(target_count).map_err(str::to_string),
        "ClassPaladin" => paladin::agent::PaladinAgent::fight(prepared)?.native_two_world_targets(target_count).map_err(str::to_string),
        "ClassPriest" => priest::agent::PriestAgent::fight(prepared)?.native_two_world_targets(target_count).map_err(str::to_string),
        "ClassRogue" => rogue::agent::RogueAgent::fight(prepared)?.native_two_world_targets(target_count).map_err(str::to_string),
        "ClassWarrior" => warrior::agent::WarriorAgent::fight(prepared)?.native_two_world_targets(target_count).map_err(str::to_string),
        "ClassHunter" => hunter::agent::HunterAgent::fight(prepared)?.native_two_world_targets(target_count).map_err(str::to_string),
        other => Err(format!("class {other} has no native fight agent")),
    }
}

"""

PREPARED_METHOD = """
/// One selected source-native actor and monotonic gsim ACKs; diagnostic only.
pub fn native_two_world_targets(prepared: &PreparedV2, target_count: usize)
    -> Result<serde_json::Value, PreparedError>
{
    check(prepared)?;
    if !crate::core::fight::world_bridge::enabled() {
        return Err(PreparedError::Invalid(
            "RUST_MULTI_WORLD_TARGETS_REQUIRES_GSIM".to_owned()));
    }
    if !(2..=100).contains(&target_count) {
        return Err(PreparedError::Invalid(
            "RUST_MULTI_WORLD_TARGET_COUNT_INVALID".to_owned()));
    }
    crate::core::fight::world_bridge::start(&prepared.request_sha256);
    crate::classes::native_two_world_targets(prepared, target_count)
        .map_err(PreparedError::Invalid)
}

"""

CLI_METHOD = """
    if args[0] == "native-world-pulls" {
        if args.len() != 5 || args[1] != "--infile" || args[3] != "--targets" {
            return Err("native-world-pulls requires --infile PREPARED_V2.json --targets 2..100".into());
        }
        let target_count = args[4].parse::<usize>()
            .map_err(|_| "native-world-pulls target count must be an integer")?;
        if !(2..=100).contains(&target_count) {
            return Err("native-world-pulls requires --targets 2..100".into());
        }
        let input = fs::read(&args[2]).map_err(|err| err.to_string())?;
        let prepared = prepared_v2(&input)?
            .ok_or("native-world-pulls requires a prepared v2 input")?;
        let report = native_two_world_targets(&prepared, target_count)
            .map_err(|err| err.to_string())?;
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
