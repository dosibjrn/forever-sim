#!/usr/bin/env python3
"""Port source-native Forever Entangling Roots periodic damage, not root/2D CC acceptance.

This is source-patching infrastructure only: ALL Warcraft mechanics execute in the
maintained MythicSim Rust fork. The true root / damage-break / world CC remains
unimplemented and MUST NOT be marked P1/P2 PASS by this incremental change.
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
    /// Source-native Forever Roots periodic damage, not yet root/break/2D CC behavior.
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
     "        // Source data owns base tick numbers. Landed Roots emits a timed root\n"
     "        // control to the acknowledged gsim world; damage-break semantics remain unimplemented.\n"
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
     "            DruidSpell::EntanglingRoots => {\n"
     "                // Entangling Roots is binary: a miss applies neither its DoT nor\n"
     "                // its world control. The same source-native result owns both.\n"
     "                let result = fight.calc_outcome(spell, target, Outcome::MagicHit);\n"
     "                if result.landed() {\n"
     "                    let dot = fight.spells[spell].dot.expect(\"Entangling Roots has a dot\");\n"
     "                    let dot = fight.dot_on(dot, target);\n"
     "                    fight.apply_dot(dot);\n"
     "                    if target == Side::Target {\n"
     "                        let duration_ns = fight.aura(fight.dots[dot].aura).duration;\n"
     "                        crate::core::fight::world_bridge::record_control(\n"
     "                            fight.now, duration_ns,\n"
     "                            format!(\"{:?}\", fight.spells[spell].id),\n"
     "                            fight.label_of(target),\n"
     "                        );\n"
     "                    }\n"
     "                }\n"
     "                fight.deal_damage(spell, result, false);\n"
     "            },", "EFFECT"),
    ("            DruidSpell::MoonfireDot | DruidSpell::InsectSwarm => fight.snapshot_dot_tick(dot),",
     "            DruidSpell::MoonfireDot | DruidSpell::InsectSwarm | DruidSpell::EntanglingRoots => {\n"
     "                fight.snapshot_dot_tick(dot)\n"
     "            }", "DOT_TICK"),
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

WORLD_BRIDGE_PATCHES = [
    ("    event_id: String,\n    native_time_ns: i64,", "    event_id: String,\n    effect_kind: String,\n    control_id: Option<String>,\n    duration_ns: Option<i64>,\n    break_semantics_status: Option<String>,\n    native_time_ns: i64,", "EVENT_FIELDS"),
    ("            event_id: format!(\"native-effect-{}\", bridge.event_ordinal),\n            native_time_ns: time_ns, damage, source_action_id: action,", "            event_id: format!(\"native-effect-{}\", bridge.event_ordinal),\n            effect_kind: \"damage\".to_owned(), control_id: None,\n            duration_ns: None, break_semantics_status: None,\n            native_time_ns: time_ns, damage, source_action_id: action,", "DAMAGE_EVENT"),
    ("    let events = std::mem::take(&mut bridge.pending);\n    let event_ids: Vec<String> = events.iter().map(|event| event.event_id.clone()).collect();", "    let events = std::mem::take(&mut bridge.pending);\n    let damage_events: Vec<&DamageEvent> = events.iter()\n        .filter(|event| event.effect_kind == \"damage\").collect();\n    let control_events: Vec<&DamageEvent> = events.iter()\n        .filter(|event| event.effect_kind == \"control\").collect();\n    let control_event_ids: Vec<String> = control_events.iter()\n        .map(|event| event.event_id.clone()).collect();\n    let event_ids: Vec<String> = events.iter().map(|event| event.event_id.clone()).collect();", "SPLIT_EVENTS"),
    ("        \"native_damage_events\": events,", "        \"native_damage_events\": damage_events,\n        \"native_control_events\": control_events,", "CONTROL_RECEIPT"),
    ("        \"RUST_WORLD_DAMAGE_ACK_EVENTS_MISMATCH\");\n    let ack_before = number(&ack, \"world_target_health_before\");", "        \"RUST_WORLD_DAMAGE_ACK_EVENTS_MISMATCH\");\n    let accepted_controls = ack[\"applied_control_event_ids\"].as_array()\n        .expect(\"RUST_WORLD_CONTROL_ACK_EVENT_IDS_MISSING\");\n    assert!(accepted_controls.len() == control_event_ids.len()\n        && accepted_controls.iter().zip(control_event_ids.iter())\n            .all(|(a, b)| a.as_str() == Some(b)),\n        \"RUST_WORLD_CONTROL_ACK_EVENTS_MISMATCH\");\n    let ack_before = number(&ack, \"world_target_health_before\");", "CONTROL_ACK"),
    ("fn send(value: &Value) {", "pub(crate) fn record_control(time_ns: i64, duration_ns: i64,\n    action: String, target_label: String) {\n    // Production records only while the acknowledged world bridge is live.\n    // Unit tests may install an in-memory capture without a peer process.\n    let test_capture = cfg!(test);\n    if !enabled() && !test_capture { return; }\n    assert!(time_ns >= 0 && duration_ns > 0, \"RUST_WORLD_CONTROL_INVALID\");\n    BRIDGE.with(|state| {\n        let mut state = state.borrow_mut();\n        let bridge = match state.as_mut() {\n            Some(bridge) => bridge,\n            None if test_capture => return,\n            None => panic!(\"RUST_WORLD_NOT_STARTED\"),\n        };\n        bridge.event_ordinal += 1;\n        bridge.pending.push(DamageEvent {\n            event_id: format!(\"native-effect-{}\", bridge.event_ordinal),\n            effect_kind: \"control\".to_owned(),\n            control_id: Some(\"root\".to_owned()),\n            duration_ns: Some(duration_ns),\n            break_semantics_status: Some(\"unimplemented\".to_owned()),\n            native_time_ns: time_ns, damage: 0.0,\n            source_action_id: action, rank: 0, landed: true, crit: false, periodic: false,\n            native_target_index: 0, native_target_unit_index: 0,\n            native_target_label: target_label,\n            native_caster_type: String::new(), native_caster_unit_index: 0,\n            native_caster_label: String::new(),\n        });\n    });\n}\n\n#[cfg(test)]\npub(crate) fn begin_test_capture() {\n    BRIDGE.with(|state| *state.borrow_mut() = Some(Bridge {\n        iteration: 0, sequence: 0, next_tick_ns: 0, last_tick_ns: -1,\n        last_health: None, previous_ack_id: String::new(),\n        source_hash: \"a\".repeat(64), event_ordinal: 0, pending: Vec::new(),\n    }));\n}\n\n#[cfg(test)]\npub(crate) fn test_control_events() -> Vec<(String, i64, String)> {\n    BRIDGE.with(|state| {\n        state.borrow().as_ref().map(|bridge| bridge.pending.iter()\n            .filter(|event| event.effect_kind == \"control\")\n            .map(|event| (\n                event.control_id.clone().unwrap_or_default(),\n                event.duration_ns.unwrap_or_default(),\n                event.source_action_id.clone(),\n            ))\n            .collect()\n        ).unwrap_or_default()\n    })\n}\n\n#[cfg(test)]\npub(crate) fn end_test_capture() {\n    BRIDGE.with(|state| *state.borrow_mut() = None);\n}\n\nfn send(value: &Value) {", "CONTROL_HELPERS"),
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


OLD_RUST_RUNTIME_TEST = "\n#[test]\nfn forever_roots_native_periodic_ticks_change_with_rank() {\n    // Production Rust executor, not a GameIR/source-catalogue assertion.\n    // Same encounter, seed and rotation; only the legally allocated rank changes.\n    fn run(rank: i32) -> (f64, String) {\n        let mut request: Value = serde_json::from_slice(\n            &fs::read(directory().join(\"balance-every-talent-at-max.request.json\")).unwrap()\n        ).unwrap();\n        let player = &mut request[\"raid\"][\"parties\"][0][\"players\"][0];\n        player[\"talentsString\"] = Value::String(format!(\"000000{rank}\"));\n        player[\"rotation\"][\"priorityList\"] = serde_json::json!([\n            {\"action\": {\n                \"castSpell\": {\"spellId\": {\"spellId\": 9853}},\n                \"condition\": {\"not\": {\"val\": {\n                    \"dotIsActive\": {\"spellId\": {\"spellId\": 9853}}\n                }}}\n            }},\n            {\"action\": {\"castSpell\": {\"spellId\": {\"spellId\": 9912}}}}\n        ]);\n        request[\"simOptions\"][\"iterations\"] = serde_json::json!(32);\n        request[\"encounter\"][\"duration\"] = serde_json::json!(60.0);\n        request[\"encounter\"][\"durationVariation\"] = serde_json::json!(0.0);\n        let prepared = forever_engine::prepare_json(\n            &serde_json::to_vec(&request).unwrap(), \"native-roots-periodic-control\"\n        ).expect(\"Forever source-native request prepares\");\n        let prepared: forever_engine::contracts::prepared_v2::PreparedV2 =\n            serde_json::from_value(prepared).expect(\"native prepared contract\");\n        let report = forever_engine::simulate_prepared(&prepared, forever_engine::RngMode::Stochastic)\n            .expect(\"selected genuine Rust combat executes Roots\");\n        let dps = report.result[\"raidMetrics\"][\"dps\"][\"avg\"].as_f64()\n            .expect(\"native real combat DPS\");\n        let first_log = report.result[\"logs\"].as_str().unwrap_or(\"\").to_owned();\n        (dps, first_log)\n    }\n\n    let (base, base_log) = run(0);\n    let (improved, improved_log) = run(3);\n    assert!(base_log.contains(\"Casting {SpellID: 9853}\"),\n        \"native Roots must actually cast, not merely be prepared: {base_log}\");\n    assert!(improved_log.contains(\"Casting {SpellID: 9853}\"),\n        \"rank-3 build must actually cast Roots: {improved_log}\");\n    assert!(base.is_finite() && base > 0.0 && improved.is_finite(),\n        \"native combat must produce finite positive damage: {base}, {improved}\");\n    assert!(improved > base,\n        \"same-seed native combat with +75% Roots tick damage should improve DPS: {base} -> {improved}\");\n}\n"

RUST_RUNTIME_TEST = """#[test]
fn forever_roots_native_periodic_ticks_change_with_rank() {
    // Production Rust executor, not a GameIR/source-catalogue assertion.
    // Same encounter, seed and rotation; only the legally allocated rank changes.
    // The prepared hit table is overridden solely to make landed/missed
    // negative/positive controls deterministic in this regression.
    fn run(rank: i32, force_miss: bool) -> (f64, String, Vec<(String, i64, String)>) {
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
        let mut prepared = forever_engine::prepare_json(
            &serde_json::to_vec(&request).unwrap(), "native-roots-periodic-control"
        ).expect("Forever source-native request prepares");
        prepared["player"]["stats"]["SpellHitPercent"] = serde_json::json!(0.0);
        prepared["player"]["attackTable"]["base_spell_miss_chance"] =
            serde_json::json!(if force_miss { 1.0 } else { 0.0 });
        prepared["target"]["stats"]["NatureResistance"] = serde_json::json!(0.0);
        let prepared: forever_engine::contracts::prepared_v2::PreparedV2 =
            serde_json::from_value(prepared).expect("native prepared contract");

        crate::core::fight::world_bridge::begin_test_capture();
        let report = forever_engine::simulate_prepared(&prepared)
            .expect("selected genuine Rust combat executes Roots");
        let controls = crate::core::fight::world_bridge::test_control_events();
        crate::core::fight::world_bridge::end_test_capture();

        let dps = report.result["raidMetrics"]["dps"]["avg"].as_f64()
            .expect("native real combat DPS");
        let first_log = report.result["logs"].as_str().unwrap_or("").to_owned();
        (dps, first_log, controls)
    }

    let (base, base_log, landed_controls) = run(0, false);
    let (improved, improved_log, _) = run(3, false);
    let (_, _, missed_controls) = run(0, true);
    assert!(base_log.contains("Casting {SpellID: 9853}"),
        "native Roots must actually cast, not merely be prepared: {base_log}");
    assert!(improved_log.contains("Casting {SpellID: 9853}"),
        "rank-3 build must actually cast Roots: {improved_log}");
    assert!(base.is_finite() && base > 0.0 && improved.is_finite(),
        "native combat must produce finite positive damage: {base}, {improved}");
    assert!(improved > base,
        "same-seed native combat with +75% Roots tick damage should improve DPS: {base} -> {improved}");
    assert!(!landed_controls.is_empty(),
        "a landed native Roots cast did not emit a world control event");
    assert!(missed_controls.is_empty(),
        "a missed native Roots cast emitted a world control event: {missed_controls:?}");
    assert!(landed_controls.iter().all(|(control, duration, action)|
        control == "root" && *duration == 27_000_000_000_i64 && action.contains("9853")),
        "native Roots control must retain source action and 27s source DoT duration: {landed_controls:?}");
}
"""


def port_text(path: str, contents: str) -> str:
    patches = {
        "src/classes/druid/prepare/balance.rs": PREP_PATCHES,
        "src/classes/druid/agent.rs": AGENT_PATCHES,
        "src/classes/druid/prepared/coverage.rs": COVERAGE_PATCHES,
        "src/contracts/prepared_v2.rs": CONTRACT_PATCHES,
        "src/classes/druid/prepare/export.rs": EXPORT_PATCHES,
        "src/core/fight/world_bridge.rs": WORLD_BRIDGE_PATCHES,
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
            if (test_name == "forever_roots_native_periodic_ticks_change_with_rank"
                    and "a landed native Roots cast did not emit a world control event" in contents):
                continue
            if f"fn {test_name}()" in contents:
                if (test_name == "forever_roots_native_periodic_ticks_change_with_rank"
                        and contents.count(OLD_RUST_RUNTIME_TEST) == 1):
                    contents = contents.replace(OLD_RUST_RUNTIME_TEST, section, 1)
                    continue
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
    "src/core/fight/world_bridge.rs",
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
    print("RUST_FOREVER_ROOTS_NATIVE_CONTROL_SOURCE_PORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
