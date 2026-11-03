#!/usr/bin/env python3
"""Port source-native Forever Entangling Roots damage and landed root/2D control.

The Rust dot application remains the hit authority. A landed Roots dot emits a
causal control event through the real Rust↔gsim world ACK; gsim owns movement and
expiry. Damage-break/rank semantics remain incomplete, so this is not P1/P2 PASS.
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
    /// Source-native Forever Roots periodic damage; landed control is sent to gsim.
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
     "        // Python or Go copy. Landed root control is bridged to gsim; damage-break\n"
     "        // semantics remain unimplemented.\n"
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
    ("    fn on_dot_gain(fight: &mut Fight<Self>, dot: DotId, behavior: DruidSpell) {
        if behavior == DruidSpell::InsectSwarm {
            let side = fight.dots[dot].side;
            insect_swarm::on_dot_gain(fight, fight.agent.insect_swarm_debuff, side);
        }
    }",
     "    fn on_dot_gain(fight: &mut Fight<Self>, dot: DotId, behavior: DruidSpell) {
        if behavior == DruidSpell::InsectSwarm {
            let side = fight.dots[dot].side;
            insect_swarm::on_dot_gain(fight, fight.agent.insect_swarm_debuff, side);
        }
        if behavior == DruidSpell::EntanglingRoots {
            // This callback only runs after the native DoT application lands.
            // Carry the native dot's exact remaining duration to the gsim world.
            let (time_ns, duration_ns, spell, side) = {
                let state = &fight.dots[dot];
                (
                    fight.now,
                    state.tick_period.saturating_mul(i64::from(state.remaining_ticks)),
                    state.spell,
                    state.side,
                )
            };
            let action = format!("{:?}", fight.spells[spell].id);
            let target_label = fight.label_of(side);
            crate::core::fight::world_bridge::record_control_applied(
                time_ns, duration_ns, "root", action, 0, target_label,
            );
        }
    }", "ROOT_CONTROL"),
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


WORLD_BRIDGE_PATCHES = [
    ("#[derive(Clone, Serialize)]\nstruct Bridge {",
     "#[derive(Clone, Serialize)]\nstruct ControlEvent {\n    event_id: String,\n    native_time_ns: i64,\n    duration_ns: i64,\n    control_id: String,\n    source_action_id: String,\n    rank: u32,\n    landed: bool,\n    native_target_index: u32,\n    native_target_unit_index: u32,\n    native_target_label: String,\n}\n\nstruct Bridge {", "CONTROL_EVENT"),
    ("    event_ordinal: u64,\n    pending: Vec<DamageEvent>,",
     "    event_ordinal: u64,\n    pending: Vec<DamageEvent>,\n    control_event_ordinal: u64,\n    pending_controls: Vec<ControlEvent>,", "BRIDGE_FIELDS"),
    ("        source_hash: source_hash.to_owned(), event_ordinal: 0,\n        pending: Vec::new(),",
     "        source_hash: source_hash.to_owned(), event_ordinal: 0,\n        pending: Vec::new(), control_event_ordinal: 0,\n        pending_controls: Vec::new(),", "START_STATE"),
    ("        assert!(bridge.pending.is_empty(), \"RUST_WORLD_UNFLUSHED_EVENTS\");",
     "        assert!(bridge.pending.is_empty() && bridge.pending_controls.is_empty(),\n            \"RUST_WORLD_UNFLUSHED_EVENTS\");", "ITERATION_PENDING"),
    ("        bridge.event_ordinal = 0;",
     "        bridge.event_ordinal = 0;\n        bridge.control_event_ordinal = 0;\n        bridge.pending_controls.clear();", "ITERATION_RESET"),
    ("        if !bridge.pending.is_empty() {\n            return Err(\"RUST_WORLD_UNACKNOWLEDGED_DAMAGE\");\n        }",
     "        if !bridge.pending.is_empty() || !bridge.pending_controls.is_empty() {\n            return Err(\"RUST_WORLD_UNACKNOWLEDGED_DAMAGE\");\n        }", "TARGET_PENDING"),
    ("        // Deliberately preserve sequence, previous_ack_id, last_tick_ns,\n        // event_ordinal and source identity across targets.",
     "        // Deliberately preserve sequence, previous_ack_id, last_tick_ns,\n        // event_ordinal, control_event_ordinal and source identity across targets.", "TARGET_PRESERVE"),
    ("event_ordinal: 9, pending: Vec::new(),",
     "event_ordinal: 9, pending: Vec::new(), control_event_ordinal: 0, pending_controls: Vec::new(),", "TEST_STATE_9"),
    ("event_ordinal: 1, pending: Vec::new(),",
     "event_ordinal: 1, pending: Vec::new(), control_event_ordinal: 0, pending_controls: Vec::new(),", "TEST_STATE_1"),
    ("event_ordinal: 3, pending: Vec::new(),",
     "event_ordinal: 3, pending: Vec::new(), control_event_ordinal: 0, pending_controls: Vec::new(),", "TEST_STATE_3"),
    ("fn send(value: &Value) {",
     "fn queue_control_event(bridge: &mut Bridge, time_ns: i64, duration_ns: i64,\n    control_id: &str, action: String, rank: u32, target_label: String) {\n    assert!(time_ns >= 0 && duration_ns > 0, \"RUST_WORLD_CONTROL_DURATION_INVALID\");\n    assert!(time_ns.checked_add(duration_ns).is_some(), \"RUST_WORLD_CONTROL_EXPIRY_OVERFLOW\");\n    assert!(!control_id.is_empty() && !action.is_empty() && !target_label.is_empty(),\n        \"RUST_WORLD_CONTROL_IDENTITY_INVALID\");\n    bridge.control_event_ordinal += 1;\n    bridge.pending_controls.push(ControlEvent {\n        event_id: format!(\"native-control-{}\", bridge.control_event_ordinal),\n        native_time_ns: time_ns, duration_ns, control_id: control_id.to_owned(),\n        source_action_id: action, rank, landed: true,\n        native_target_index: 0, native_target_unit_index: 0,\n        native_target_label: target_label,\n    });\n    // Flush a landed control before the next native decision. gsim requires\n    // strictly increasing milliseconds, so same-time events use +1ms.\n    let earliest = if bridge.last_tick_ns < 0 { 0 }\n        else { bridge.last_tick_ns.saturating_add(1_000_000) };\n    bridge.next_tick_ns = bridge.next_tick_ns.min(time_ns.max(earliest));\n}\n\npub(crate) fn record_control_applied(time_ns: i64, duration_ns: i64,\n    control_id: &str, action: String, rank: u32, target_label: String) {\n    if !enabled() { return; }\n    BRIDGE.with(|state| {\n        let mut state = state.borrow_mut();\n        let bridge = state.as_mut().expect(\"RUST_WORLD_NOT_STARTED\");\n        queue_control_event(bridge, time_ns, duration_ns, control_id, action, rank, target_label);\n    });\n}\n\nfn send(value: &Value) {", "QUEUE_CONTROL"),
    ("    let events = std::mem::take(&mut bridge.pending);\n    let event_ids: Vec<String> = events.iter().map(|event| event.event_id.clone()).collect();",
     "    let events = std::mem::take(&mut bridge.pending);\n    let event_ids: Vec<String> = events.iter().map(|event| event.event_id.clone()).collect();\n    let control_events = std::mem::take(&mut bridge.pending_controls);\n    let control_event_ids: Vec<String> = control_events.iter()\n        .map(|event| event.event_id.clone()).collect();", "EXCHANGE_CONTROL_EVENTS"),
    ("        \"native_damage_events\": events,\n        \"native_range_receipt\": {",
     "        \"native_damage_events\": events,\n        \"native_control_events\": control_events,\n        \"native_range_receipt\": {", "RECEIPT_CONTROL_EVENTS"),
    ("        \"RUST_WORLD_DAMAGE_ACK_EVENTS_MISMATCH\");\n    let ack_before = number(&ack, \"world_target_health_before\");",
     "        \"RUST_WORLD_DAMAGE_ACK_EVENTS_MISMATCH\");\n    let accepted_controls = ack[\"applied_control_event_ids\"].as_array()\n        .expect(\"RUST_WORLD_CONTROL_ACK_EVENT_IDS_MISSING\");\n    assert!(accepted_controls.len() == control_event_ids.len()\n        && accepted_controls.iter().zip(control_event_ids.iter())\n            .all(|(a,b)| a.as_str() == Some(b)),\n        \"RUST_WORLD_CONTROL_ACK_EVENTS_MISMATCH\");\n    let ack_before = number(&ack, \"world_target_health_before\");", "ACK_CONTROL_EVENTS"),
    ("            && bridge.previous_ack_id.len() == 64 && bridge.pending.is_empty()",
     "            && bridge.previous_ack_id.len() == 64 && bridge.pending.is_empty()\n            && bridge.pending_controls.is_empty()", "LETHAL_PENDING"),
    ("        assert!(bridge.pending.is_empty(), \"RUST_WORLD_FINISH_UNFLUSHED\");",
     "        assert!(bridge.pending.is_empty() && bridge.pending_controls.is_empty(),\n            \"RUST_WORLD_FINISH_UNFLUSHED\");", "FINISH_PENDING"),
    ("pub(crate) fn due(next_native_ns: i64, end_ns: i64) -> Option<i64> {",
     "#[cfg(test)]\nmod native_control_event_tests {\n    use super::*;\n\n    fn test_bridge() -> Bridge {\n        Bridge {\n            iteration: 0, sequence: 1, next_tick_ns: 2_000_000_000,\n            last_tick_ns: 1_000_000_000, last_health: Some(100.0),\n            previous_ack_id: \"a\".repeat(64), source_hash: \"b\".repeat(64),\n            event_ordinal: 0, pending: Vec::new(),\n            control_event_ordinal: 0, pending_controls: Vec::new(),\n        }\n    }\n\n    #[test]\n    fn landed_root_requests_world_ack_at_native_dot_gain_before_next_action() {\n        let mut bridge = test_bridge();\n        queue_control_event(&mut bridge, 1_500_000_000, 27_000_000_000,\n            \"root\", \"SpellID:9853\".to_owned(), 0, \"Target\".to_owned());\n        assert_eq!(bridge.next_tick_ns, 1_500_000_000);\n        assert_eq!(bridge.pending_controls.len(), 1);\n        let event = &bridge.pending_controls[0];\n        assert_eq!(event.event_id, \"native-control-1\");\n        assert_eq!(event.native_time_ns, 1_500_000_000);\n        assert_eq!(event.duration_ns, 27_000_000_000);\n        assert_eq!(event.control_id, \"root\");\n        assert_eq!(event.source_action_id, \"SpellID:9853\");\n        assert!(event.landed);\n    }\n\n    #[test]\n    fn root_at_previous_ack_time_is_flushed_on_next_gsim_millisecond() {\n        let mut bridge = test_bridge();\n        bridge.last_tick_ns = 1_500_000_000;\n        queue_control_event(&mut bridge, 1_500_000_000, 27_000_000_000,\n            \"root\", \"SpellID:9853\".to_owned(), 0, \"Target\".to_owned());\n        assert_eq!(bridge.next_tick_ns, 1_501_000_000);\n    }\n}\n\npub(crate) fn due(next_native_ns: i64, end_ns: i64) -> Option<i64> {", "CONTROL_TESTS"),
];

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
    print("RUST_FOREVER_ROOTS_DOT_SOURCE_PORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
