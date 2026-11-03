#!/usr/bin/env python3
"""Port source-native Forever Entangling Roots periodic damage and landed 2D root control.

The Rust source owns the landed DoT/control event and its native duration; the
actual gsim CombatRuntime owns 2D immobilization and expiry. Damage-break
semantics and full P1/P2 gate acceptance remain unimplemented.
"""
from __future__ import annotations

from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str, label: str) -> str:
    # The replacement may intentionally retain the old anchor (e.g. adding a
    # line after a declaration); recognizing the whole replacement is idempotent.
    if source.count(new) == 1:
        return source
    if source.count(old) != 1 or new in source:
        raise ValueError("NATIVE_ROOTS_" + label + "_SOURCE_DRIFT")
    return source.replace(old, new, 1)


ROOTS_METHOD = """
    /// Source-native Forever Roots periodic damage; landed control is bridged separately.
    /// Keep GoReference preparation unchanged for the pinned Go goldens.
    fn register_entangling_roots_spell(&mut self, sim: &mut Sim) {
        let rank = Ladder::ranked(&ENTANGLING_ROOTS_RANKS).highest();
        let tick = rank.periodic_effect();
        self.register_spell(
            sim,
            HUMANOID | MOONKIN,
            SpellConfig {
                action_id: ActionId::spell(rank.id),
                spell_school: rank.spell_school(),
                defense_type: rank.defense_type_core(),
                proc_mask: ProcMask::SPELL_DAMAGE,
                class_spell_mask: masks::ENTANGLING_ROOTS,
                flags: SpellFlag::APL | SpellFlag::BINARY,
                rank: rank.rank_number(),
                damage_multiplier: 1.0,
                threat_multiplier: 1.0,
                max_range: f64::from(rank.max_range),
                cost: flat_mana(rank),
                cast: CastConfig {
                    default_cast: Cast {
                        gcd: rank.gcd(),
                        cast_time: rank.cast_time(),
                        ..Cast::default()
                    },
                    ..CastConfig::default()
                },
                dot: DotConfig {
                    aura: AuraConfig {
                        label: "Entangling Roots".to_string(),
                        ..AuraConfig::default()
                    },
                    number_of_ticks: (rank.duration() / tick.period()) as i32,
                    tick_length: tick.period(),
                    affected_by_cast_speed: false,
                    bonus_coefficient: tick.coeff(),
                    // Forever: +25/50/75% periodic damage at talent ranks 1/2/3.
                    periodic_damage_multiplier: 1.0
                        + 0.25 * f64::from(self.tal.improved_entangling_roots),
                    ..DotConfig::default()
                },
                ..SpellConfig::default()
            },
        );
    }

"""

PREP_PATCHES = [
    ("const INSECT_SWARM_RANKS: [i32; 5] = [5570, 24974, 24975, 24976, 24977];",
     "const INSECT_SWARM_RANKS: [i32; 5] = [5570, 24974, 24975, 24976, 24977];\n"
     "const ENTANGLING_ROOTS_RANKS: [i32; 6] = [339, 1062, 5195, 5196, 9852, 9853];",
     "RANKS"),
    ("        self.register_hurricane_spell(sim);\n        self.register_faerie_fire_spell(sim);",
     "        self.register_hurricane_spell(sim);\n        self.register_faerie_fire_spell(sim);\n"
     "        // The Go oracle does not register this Forever-only client spell.\n"
     "        if sim.rules == Rules::Forever {\n"
     "            self.register_entangling_roots_spell(sim);\n"
     "        }", "REGISTER"),
    ("    /// Go " + chr(96) + "registerStarfireSpell" + chr(96) + ": every rank is registered.",
     ROOTS_METHOD + "    /// Go " + chr(96) + "registerStarfireSpell" + chr(96)
     + ": every rank is registered.", "METHOD"),
]

AGENT_PATCHES = [
    ("    InsectSwarm,\n    Innervate,",
     "    InsectSwarm,\n    EntanglingRoots,\n    Innervate,", "ENUM"),
    ('            "insect_swarm" if spell.dot.is_some() => Some(DruidSpell::InsectSwarm),',
     '            "insect_swarm" if spell.dot.is_some() => Some(DruidSpell::InsectSwarm),\n'
     '            "entangling_roots" if spell.dot.is_some() => Some(DruidSpell::EntanglingRoots),',
     "SPELL"),
    ("        for effect in &prepared.effects {\n            match effect {\n                Effect::Heals {",
     "        // Native-only Forever spell: source data owns base tick numbers, not a\n"
     "        // Python or Go copy. The landed root is bridged to gsim; damage-break\n"
     "        // semantics remain unmodeled and must not be treated as a full CC PASS.\n"
     "        if let Some(roots) = find_spell(&fight, 9853, 0) {\n"
     "            let dot = fight.spells[roots].dot.ok_or(\"Entangling Roots lacks its dot\")?;\n"
     "            let row = crate::prepare::spelldata::Ladder::ranked(&[9853]).highest();\n"
     "            fight.dots[dot].tick_base = Some(row.periodic_effect().average(\n"
     "                crate::prepare::character::constants::CHARACTER_LEVEL,\n"
     "            ));\n"
     "            fight.dots[dot].tick_can_crit = row.periodic_can_crit();\n"
     "        }\n"
     "        for effect in &prepared.effects {\n            match effect {\n                Effect::Heals {", "TICK_BASE"),
    ("            DruidSpell::InsectSwarm => insect_swarm::apply(fight, spell, target),",
     "            DruidSpell::InsectSwarm => insect_swarm::apply(fight, spell, target),\n"
     "            DruidSpell::EntanglingRoots => insect_swarm::apply(fight, spell, target),", "EFFECT"),
    ("            DruidSpell::MoonfireDot | DruidSpell::InsectSwarm => fight.snapshot_dot_tick(dot),",
     "            DruidSpell::MoonfireDot | DruidSpell::InsectSwarm | DruidSpell::EntanglingRoots => {\n"
     "                fight.snapshot_dot_tick(dot)\n"
     "            }", "DOT_TICK"),
    ("    fn on_dot_gain(fight: &mut Fight<Self>, dot: DotId, behavior: DruidSpell) {\n"
     "        if behavior == DruidSpell::InsectSwarm {\n"
     "            let side = fight.dots[dot].side;\n"
     "            insect_swarm::on_dot_gain(fight, fight.agent.insect_swarm_debuff, side);\n"
     "        }\n"
     "    }",
     "    fn on_dot_gain(fight: &mut Fight<Self>, dot: DotId, behavior: DruidSpell) {\n"
     "        if behavior == DruidSpell::InsectSwarm {\n"
     "            let side = fight.dots[dot].side;\n"
     "            insect_swarm::on_dot_gain(fight, fight.agent.insect_swarm_debuff, side);\n"
     "        }\n"
     "        // This callback runs only after the native binary spell gained its DoT: a miss\n"
     "        // cannot create a control event. The selected 2D world owns movement and expiry.\n"
     "        if behavior == DruidSpell::EntanglingRoots {\n"
     "            let root = &fight.dots[dot];\n"
     "            if root.side == Side::Target {\n"
     "                let duration_ns = i64::from(root.remaining_ticks)\n"
     "                    .checked_mul(root.tick_period)\n"
     "                    .filter(|duration| *duration > 0)\n"
     "                    .expect(\"RUST_WORLD_ROOT_DURATION_INVALID\");\n"
     "                let action = format!(\"{:?}\", fight.spells[root.spell].id);\n"
     "                crate::core::fight::world_bridge::record_control(\n"
     "                    fight.now, duration_ns, \"root\", action, \"Target\".to_owned(),\n"
     "                );\n"
     "            }\n"
     "        }\n"
     "    }", "ROOT_CONTROL"),
]

CONTRACT_PATCHES = [
    ("    InsectSwarm {\n        rank: FireballRank,\n        debuff_aura: String,\n    },\n    /// Innervate's cast",
     "    InsectSwarm {\n        rank: FireballRank,\n        debuff_aura: String,\n    },\n    /// Source-native Forever Entangling Roots: timed periodic combat occurs in the Druid agent.\n    EntanglingRoots {},\n    /// Innervate's cast", "VARIANT"),
    ("            Effect::InsectSwarm { .. } => \"insect_swarm\",\n            Effect::Innervate",
     "            Effect::InsectSwarm { .. } => \"insect_swarm\",\n            Effect::EntanglingRoots {} => \"entangling_roots\",\n            Effect::Innervate", "KIND"),
]

EXPORT_PATCHES = [
    ("        let target = env.encounter.targets[0];\n        if self.tal.insect_swarm {",
     "        // A real, registered Forever-only native Druid spell; this typed\n        // capability authorizes the existing Rust cast/DoT handler.\n        if sim.rules == crate::prepare::sim::Rules::Forever {\n            effects.push(json!({\"kind\": \"entangling_roots\"}));\n        }\n        let target = env.encounter.targets[0];\n        if self.tal.insect_swarm {", "EXPORT"),
]

COVERAGE_PATCHES = [
    ("    \"enrage\",\n    \"faerie_fire\",",
     "    \"enrage\",\n    \"entangling_roots\",\n    \"faerie_fire\",", "CAPABILITY"),
    ('        "insect_swarm" if spell.dot.is_some() => Some("insect_swarm"),',
     '        "insect_swarm" if spell.dot.is_some() => Some("insect_swarm"),\n'
     '        "entangling_roots" if spell.dot.is_some() => Some("entangling_roots"),', "COVERAGE"),
]

RUST_TEST = """
#[test]
fn forever_roots_preparation_uses_native_spell_data_and_improved_rank() {
    let original: Value = serde_json::from_slice(
        &fs::read(directory().join("balance-every-talent-at-max.request.json")).unwrap()
    ).unwrap();
    for (rank, multiplier) in [(0, 1.0), (1, 1.25), (2, 1.5), (3, 1.75)] {
        let mut request = original.clone();
        let player = &mut request["raid"]["parties"][0]["players"][0];
        // The all-talents-max fixture is intentionally illegal under Forever:
        // Predatory Discipline has one rank, not the three in that Go fixture.
        // Exercise the real legal Forever talent layout with only Roots selected.
        player["talentsString"] = Value::String(format!("000000{rank}"));
        let prepared = forever_engine::prepare_json(
            &serde_json::to_vec(&request).unwrap(),
            "native-roots-rank",
        ).expect("Forever Druid prepares");
        let roots = prepared["player"]["spells"].as_array().unwrap().iter()
            .find(|spell| spell["action_id"]["spell_id"] == 9853)
            .expect("source-native Rank 6 Entangling Roots");
        assert_eq!(roots["class_spell"], "entangling_roots");
        let dot = &roots["dot"];
        assert_eq!(dot["base_tick_count"], 9);
        assert_eq!(dot["base_tick_length_ns"], 3_000_000_000_i64);
        assert_eq!(dot["periodic_damage_multiplier"].as_f64(), Some(multiplier));
    }
}
"""


RUST_RUNTIME_TEST = """
#[test]
fn forever_roots_native_periodic_ticks_change_with_rank() {
    // Production Rust executor, not a GameIR/source-catalogue assertion.
    // Same encounter, seed and rotation; only the legally allocated rank changes.
    fn run(rank: i32) -> (f64, String) {
        let mut request: Value = serde_json::from_slice(
            &fs::read(directory().join("balance-every-talent-at-max.request.json")).unwrap()
        ).unwrap();
        let player = &mut request["raid"]["parties"][0]["players"][0];
        player["talentsString"] = Value::String(format!("000000{rank}"));
        player["rotation"]["priorityList"] = serde_json::json!([
            {"action": {
                "castSpell": {"spellId": {"spellId": 9853}},
                "condition": {"not": {"val": {
                    "dotIsActive": {"spellId": {"spellId": 9853}}
                }}}
            }},
            {"action": {"castSpell": {"spellId": {"spellId": 9912}}}}
        ]);
        request["simOptions"]["iterations"] = serde_json::json!(32);
        request["encounter"]["duration"] = serde_json::json!(60.0);
        request["encounter"]["durationVariation"] = serde_json::json!(0.0);
        let prepared = forever_engine::prepare_json(
            &serde_json::to_vec(&request).unwrap(), "native-roots-periodic-control"
        ).expect("Forever source-native request prepares");
        let prepared: forever_engine::contracts::prepared_v2::PreparedV2 =
            serde_json::from_value(prepared).expect("native prepared contract");
        let report = forever_engine::simulate_prepared(&prepared)
            .expect("selected genuine Rust combat executes Roots");
        let dps = report.result["raidMetrics"]["dps"]["avg"].as_f64()
            .expect("native real combat DPS");
        let first_log = report.result["logs"].as_str().unwrap_or("").to_owned();
        (dps, first_log)
    }

    let (base, base_log) = run(0);
    let (improved, improved_log) = run(3);
    assert!(base_log.contains("Casting {SpellID: 9853}"),
        "native Roots must actually cast, not merely be prepared: {base_log}");
    assert!(improved_log.contains("Casting {SpellID: 9853}"),
        "rank-3 build must actually cast Roots: {improved_log}");
    assert!(base.is_finite() && base > 0.0 && improved.is_finite(),
        "native combat must produce finite positive damage: {base}, {improved}");
    assert!(improved > base,
        "same-seed native combat with +75% Roots tick damage should improve DPS: {base} -> {improved}");
}
"""


def port_text(path: str, contents: str) -> str:
    patches = {
        "src/classes/druid/prepare/balance.rs": PREP_PATCHES,
        "src/classes/druid/agent.rs": AGENT_PATCHES,
        "src/classes/druid/prepared/coverage.rs": COVERAGE_PATCHES,
        "src/contracts/prepared_v2.rs": CONTRACT_PATCHES,
        "src/classes/druid/prepare/export.rs": EXPORT_PATCHES,
    }
    if path in patches:
        for old, new, label in patches[path]:
            contents = replace_once(contents, old, new, label)
        return contents
    if path == "tests/classes/druid/prepare.rs":
        for test_name, section in (
            ("forever_roots_preparation_uses_native_spell_data_and_improved_rank", RUST_TEST),
            ("forever_roots_native_periodic_ticks_change_with_rank", RUST_RUNTIME_TEST),
        ):
            if section in contents:
                continue
            if f"fn {test_name}()" in contents:
                raise ValueError("NATIVE_ROOTS_TEST_SOURCE_DRIFT:" + test_name)
            contents = contents.rstrip() + "\n" + section
        return contents
    raise ValueError("unsupported port target " + path)


PATHS = [
    "src/classes/druid/prepare/balance.rs",
    "src/classes/druid/agent.rs",
    "src/classes/druid/prepared/coverage.rs",
    "src/contracts/prepared_v2.rs",
    "src/classes/druid/prepare/export.rs",
    "tests/classes/druid/prepare.rs",
]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_entangling_roots_dot.py RUST_ENGINE_ROOT")
    root = Path(argv[1])
    original = {path: (root / path).read_text() for path in PATHS}
    result = {path: port_text(path, original[path]) for path in PATHS}
    for path, text in result.items():
        if text != original[path]:
            (root / path).write_text(text)
    print("RUST_FOREVER_ROOTS_DOT_SOURCE_PORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
