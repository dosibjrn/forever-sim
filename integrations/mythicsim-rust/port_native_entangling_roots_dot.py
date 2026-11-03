#!/usr/bin/env python3
"""Port source-native Forever Entangling Roots damage and landed root control.

The selected Rust source owns rank, hit, cast, dot lifetime and periodic damage.
A landed native Roots dot publishes its exact target-control expiry to gsim's
existing 2D root behavior. Damage-break and rank/target-cap semantics remain
incomplete; this is not a P1/P2 acceptance pass.
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
    /// Source-native Forever Roots periodic damage; landed root lifetime is bridged to gsim.
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
     "        // Python or Go copy. Root/break and real 2D CC remain unimplemented.\n"
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
     "        if behavior == DruidSpell::EntanglingRoots {\n"
     "            let state = &fight.dots[dot];\n"
     "            assert!(matches!(state.side, crate::core::fight::Side::Target),\n"
     "                \"RUST_WORLD_ROOT_CONTROL_TARGET_NOT_PRIMARY\");\n"
     "            let duration_ns = state.tick_period.checked_mul(i64::from(state.remaining_ticks))\n"
     "                .expect(\"RUST_WORLD_ROOT_DURATION_OVERFLOW\");\n"
     "            let expires_at_ns = fight.now.checked_add(duration_ns)\n"
     "                .expect(\"RUST_WORLD_ROOT_EXPIRY_OVERFLOW\");\n"
     "            crate::core::fight::world_bridge::record_root_control(fight.now, Some(expires_at_ns));\n"
     "        }\n"
     "    }", "ROOT_GAIN"),
    ("        if behavior == DruidSpell::InsectSwarm {\n"
     "            let side = fight.dots[dot].side;\n"
     "            insect_swarm::on_dot_expire(fight, fight.agent.insect_swarm_debuff, side);\n"
     "        }\n"
     "    }",
     "        if behavior == DruidSpell::InsectSwarm {\n"
     "            let side = fight.dots[dot].side;\n"
     "            insect_swarm::on_dot_expire(fight, fight.agent.insect_swarm_debuff, side);\n"
     "        }\n"
     "        if behavior == DruidSpell::EntanglingRoots {\n"
     "            let side = fight.dots[dot].side;\n"
     "            assert!(matches!(side, crate::core::fight::Side::Target),\n"
     "                \"RUST_WORLD_ROOT_CONTROL_TARGET_NOT_PRIMARY\");\n"
     "            crate::core::fight::world_bridge::record_root_control(fight.now, None);\n"
     "        }\n"
     "    }", "ROOT_EXPIRE"),
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



ROOT_CONTROL_BLOCK = """
// The native Druid agent reports only a landed Roots dot's actual expiry.
// Keep this separate from damage events: it is a typed world-control receipt.
#[derive(Clone, Copy, Default)]
struct RootControlState {
    expires_at_ns: Option<i64>,
    changed_at_ns: Option<i64>,
    acknowledged_expires_at_ns: Option<i64>,
}
thread_local! {
    static ROOT_CONTROL: RefCell<RootControlState> = const { RefCell::new(RootControlState {
        expires_at_ns: None,
        changed_at_ns: None,
        acknowledged_expires_at_ns: None,
    }) };
}
fn root_control_snapshot() -> RootControlState {
    ROOT_CONTROL.with(|state| *state.borrow())
}
fn reset_root_control() {
    ROOT_CONTROL.with(|state| *state.borrow_mut() = RootControlState::default());
}
fn root_control_for_receipt(clock_ns: i64) -> (RootControlState, bool) {
    let state = root_control_snapshot();
    let change_due = state.changed_at_ns
        .map(|changed_at_ns| changed_at_ns <= clock_ns)
        .unwrap_or(false);
    if change_due {
        (state, true)
    } else {
        (RootControlState {
            expires_at_ns: state.acknowledged_expires_at_ns,
            changed_at_ns: None,
            acknowledged_expires_at_ns: state.acknowledged_expires_at_ns,
        }, false)
    }
}
fn acknowledge_root_control(receipt: RootControlState) {
    ROOT_CONTROL.with(|state| {
        let mut state = state.borrow_mut();
        if state.expires_at_ns == receipt.expires_at_ns
            && state.changed_at_ns == receipt.changed_at_ns
        {
            state.acknowledged_expires_at_ns = state.expires_at_ns;
            state.changed_at_ns = None;
        }
    });
}
pub(crate) fn record_root_control(at_ns: i64, expires_at_ns: Option<i64>) {
    // No bridge means no world-side effect. Ordinary native-only fights remain unchanged.
    if !BRIDGE.with(|state| state.borrow().is_some()) {
        return;
    }
    let changed_at_ns = at_ns.max(0);
    let expires_at_ns = expires_at_ns.filter(|expiry| *expiry > changed_at_ns);
    ROOT_CONTROL.with(|state| {
        let mut state = state.borrow_mut();
        if state.expires_at_ns != expires_at_ns {
            state.expires_at_ns = expires_at_ns;
            state.changed_at_ns = Some(changed_at_ns);
        }
    });
}
"""

WORLD_BRIDGE_PATCHES = [
    (
        "thread_local! {\\n    static BRIDGE: RefCell<Option<Bridge>> = const { RefCell::new(None) };\\n}\\n",
        "thread_local! {\\n    static BRIDGE: RefCell<Option<Bridge>> = const { RefCell::new(None) };\\n}\\n\\n" + ROOT_CONTROL_BLOCK,
        "ROOT_STATE",
    ),
    (
        "        source_hash: source_hash.to_owned(), event_ordinal: 0,\\n        pending: Vec::new(),\\n    }));\\n}",
        "        source_hash: source_hash.to_owned(), event_ordinal: 0,\\n        pending: Vec::new(),\\n    }));\\n    reset_root_control();\\n}",
        "ROOT_START_RESET",
    ),
    (
        "        bridge.event_ordinal = 0;\\n    });\\n}",
        "        bridge.event_ordinal = 0;\\n        reset_root_control();\\n    });\\n}",
        "ROOT_ITERATION_RESET",
    ),
    (
        "        bridge.next_tick_ns = at_ns;\\n        // Deliberately preserve sequence, previous_ack_id, last_tick_ns,",
        "        bridge.next_tick_ns = at_ns;\\n        reset_root_control();\\n        // Deliberately preserve sequence, previous_ack_id, last_tick_ns,",
        "ROOT_TARGET_RESET",
    ),
    (
        "        (boundary >= 0 && boundary > bridge.last_tick_ns\\n            && boundary <= next_native_ns && boundary <= end_ns)\\n            .then_some(boundary)",
        """        // A source-native Roots gain/expiry is a real world boundary. Round
        // upward to gsim's millisecond clock and never jump over an earlier
        // independent world deadline.
        let root = root_control_snapshot();
        let root_boundary = root.changed_at_ns.map(|changed_at_ns| {
            let rounded = changed_at_ns.saturating_add(999_999) / 1_000_000 * 1_000_000;
            let earliest = if bridge.last_tick_ns < 0 {
                0
            } else {
                bridge.last_tick_ns.saturating_add(1_000_000)
            };
            rounded.max(earliest)
        }).filter(|candidate| *candidate >= 0
            && *candidate <= next_native_ns && *candidate <= end_ns);
        let boundary = root_boundary.map(|candidate| candidate.min(boundary)).unwrap_or(boundary);
        (boundary >= 0 && boundary > bridge.last_tick_ns
            && boundary <= next_native_ns && boundary <= end_ns)
            .then_some(boundary)""",
        "ROOT_DUE",
    ),
    (
        "    let events = std::mem::take(&mut bridge.pending);",
        "    let (root_control, root_control_change_due) = root_control_for_receipt(clock_ns);\\n    let events = std::mem::take(&mut bridge.pending);",
        "ROOT_EXCHANGE_SNAPSHOT",
    ),
    (
        "            \\"native_encounter_damage\\": cumulative_damage,\\n            \\"facing_applied\\": true, \\"in_front_of_target\\": front",
        "            \\"native_encounter_damage\\": cumulative_damage,\\n            \\"native_rooted_until_ns\\": root_control.expires_at_ns,\\n            \\"native_root_control_changed_at_ns\\": root_control.changed_at_ns,\\n            \\"facing_applied\\": true, \\"in_front_of_target\\": front",
        "ROOT_RECEIPT",
    ),
    (
        "    let ack = receive();\\n    assert!(ack[\\"type\\"] == \\"gsim_native_damage_applied_ack\\"",
        """    let ack = receive();
    assert!(ack.get("native_rooted_until_ns").is_some()
        && ack["native_rooted_until_ns"].as_i64() == root_control.expires_at_ns,
        "RUST_WORLD_ROOT_CONTROL_ACK_MISMATCH");
    assert!(ack.get("native_root_control_changed_at_ns").is_some()
        && ack["native_root_control_changed_at_ns"].as_i64() == root_control.changed_at_ns,
        "RUST_WORLD_ROOT_CONTROL_CHANGE_ACK_MISMATCH");
    let expected_rooted = root_control.expires_at_ns
        .map(|expiry| expiry > clock_ns).unwrap_or(false);
    assert!(ack["world_target_rooted"].as_bool() == Some(expected_rooted),
        "RUST_WORLD_ROOT_CONTROL_STATE_ACK_MISMATCH");
    assert!(ack["type"] == "gsim_native_damage_applied_ack" """,
        "ROOT_ACK",
    ),
    (
        "    bridge.next_tick_ns = next_world_boundary_ns;\\n    BRIDGE.with(|state| *state.borrow_mut() = Some(bridge));",
        "    bridge.next_tick_ns = next_world_boundary_ns;\\n    if root_control_change_due { acknowledge_root_control(root_control); }\\n    BRIDGE.with(|state| *state.borrow_mut() = Some(bridge));",
        "ROOT_ACKNOWLEDGE_CHANGE",
    ),
]

RUST_ROOT_CONTROL_TEST = """
#[cfg(test)]
mod native_root_control_bridge_tests {
    use super::*;

    #[test]
    fn landed_root_gain_and_expiry_force_world_boundaries_without_future_leakage() {
        BRIDGE.with(|slot| *slot.borrow_mut() = Some(Bridge {
            iteration: 0, sequence: 0, next_tick_ns: 100_000_000,
            last_tick_ns: -1, last_health: None, previous_ack_id: String::new(),
            source_hash: "b".repeat(64), event_ordinal: 0, pending: Vec::new(),
        }));
        reset_root_control();

        // No landed native dot (the miss negative control) means no world CC.
        let (miss, changed) = root_control_for_receipt(0);
        assert!(!changed);
        assert_eq!(miss.expires_at_ns, None);
        assert_eq!(due(100_000_000, 60_000_000_000), Some(100_000_000));

        record_root_control(50_000_000, Some(27_050_000_000));
        assert_eq!(due(100_000_000, 60_000_000_000), Some(50_000_000));
        let (before_gain, changed) = root_control_for_receipt(49_000_000);
        assert!(!changed);
        assert_eq!(before_gain.expires_at_ns, None);
        let (gain_receipt, changed) = root_control_for_receipt(50_000_000);
        assert!(changed);
        assert_eq!(gain_receipt.expires_at_ns, Some(27_050_000_000));
        acknowledge_root_control(gain_receipt);

        BRIDGE.with(|slot| {
            let mut slot = slot.borrow_mut();
            let bridge = slot.as_mut().unwrap();
            bridge.last_tick_ns = 50_000_000;
            bridge.next_tick_ns = 150_000_000;
        });
        assert_eq!(due(150_000_000, 60_000_000_000), Some(150_000_000));

        BRIDGE.with(|slot| {
            let mut slot = slot.borrow_mut();
            let bridge = slot.as_mut().unwrap();
            bridge.last_tick_ns = 27_000_000_000;
            bridge.next_tick_ns = 27_100_000_000;
        });
        record_root_control(27_050_000_000, None);
        assert_eq!(due(27_100_000_000, 60_000_000_000), Some(27_050_000_000));
        let (before_expiry, changed) = root_control_for_receipt(27_049_000_000);
        assert!(!changed);
        assert_eq!(before_expiry.expires_at_ns, Some(27_050_000_000));
        let (expiry_receipt, changed) = root_control_for_receipt(27_050_000_000);
        assert!(changed);
        assert_eq!(expiry_receipt.expires_at_ns, None);
        acknowledge_root_control(expiry_receipt);
        assert_eq!(root_control_snapshot().acknowledged_expires_at_ns, None);

        reset_root_control();
        BRIDGE.with(|slot| *slot.borrow_mut() = None);
    }
}
"""

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
    if path == "src/core/fight/world_bridge.rs":
        for old, new, label in WORLD_BRIDGE_PATCHES:
            if label == "ROOT_RECEIPT":
                has_expiry = "native_rooted_until_ns" in contents
                has_change = "native_root_control_changed_at_ns" in contents
                if has_expiry and has_change:
                    continue  # The later gsim-moving port appends its own receipt field.
                if has_expiry or has_change:
                    raise ValueError("NATIVE_ROOTS_RECEIPT_PARTIAL_SOURCE_DRIFT")
            contents = replace_once(contents, old, new, label)
        if RUST_ROOT_CONTROL_TEST not in contents:
            if "fn landed_root_gain_and_expiry_force_world_boundaries()" in contents:
                raise ValueError("NATIVE_ROOTS_BRIDGE_TEST_SOURCE_DRIFT")
            contents = contents.rstrip() + "\n" + RUST_ROOT_CONTROL_TEST
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
    "src/core/fight/world_bridge.rs",
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
    print("RUST_FOREVER_ROOTS_DOT_AND_WORLD_CONTROL_SOURCE_PORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
