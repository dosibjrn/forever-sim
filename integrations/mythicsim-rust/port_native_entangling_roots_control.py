#!/usr/bin/env python3
"""Port landed/expired native Entangling Roots control through the real gsim ACK.

This does not implement damage-break probability or certify P1/P2. Rust owns
the binary hit roll and DoT lifetime; gsim applies the resulting generic root
state to its actual 2D target motion and acknowledges the world hash.
"""
from __future__ import annotations

from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str, label: str) -> str:
    if source.count(new) == 1:
        return source
    if source.count(old) != 1 or new in source:
        raise ValueError("NATIVE_ROOTS_CONTROL_" + label + "_SOURCE_DRIFT")
    return source.replace(old, new, 1)


ROOTS_MODULE = r'''//! Entangling Roots (9853): native binary hit, source DoT and world-control receipts.
use crate::core::fight::{Agent, Fight, Outcome, Side, SpellId};

pub(crate) fn apply<A: Agent>(fight: &mut Fight<A>, spell: SpellId, target: Side) {
    let result = fight.calc_outcome(spell, target, Outcome::MagicHit);
    let rank_spell_id = fight.spells[spell].id.spell_id;
    let action = format!("spell:{}", rank_spell_id);
    let target_index = target.target_position()
        .expect("Entangling Roots must target an encounter enemy") as u32;
    crate::core::fight::world_bridge::record_control_attempt(
        fight.now, result.landed(), action, rank_spell_id, target_index, format!("{:?}", target),
    );
    if result.landed() {
        let dot = fight.spells[spell].dot.expect("Entangling Roots has a DoT");
        fight.apply_dot(fight.dot_on(dot, target));
    }
    fight.deal_damage(spell, result, false);
}
'''

AGENT_PATCHES = [
    (
        "        hurricane, innervate, insect_swarm, moonfire,",
        "        entangling_roots, hurricane, innervate, insect_swarm, moonfire,",
        "IMPORT",
    ),
    (
        "            DruidSpell::EntanglingRoots => insect_swarm::apply(fight, spell, target),",
        "            DruidSpell::EntanglingRoots => entangling_roots::apply(fight, spell, target),",
        "APPLY",
    ),
    (
        "        // Native-only Forever spell: source data owns base tick numbers, not a\\n"
        "        // Python or Go copy. Root/break and real 2D CC remain unimplemented.\\n",
        "        // Native-only Forever spell: source data owns base tick numbers, not a\\n"
        "        // Python or Go copy. Root lifetime is source-native and ACKed by gsim;\\n"
        "        // damage-break probability remains a separate native slice.\\n",
        "ROOT_COMMENT",
    ),
    (
        "        if behavior == DruidSpell::InsectSwarm {\n"
        "            let side = fight.dots[dot].side;\n"
        "            insect_swarm::on_dot_gain(fight, fight.agent.insect_swarm_debuff, side);\n"
        "        }",
        "        if behavior == DruidSpell::InsectSwarm {\n"
        "            let side = fight.dots[dot].side;\n"
        "            insect_swarm::on_dot_gain(fight, fight.agent.insect_swarm_debuff, side);\n"
        "        }\n"
        "        if behavior == DruidSpell::EntanglingRoots {\n"
        "            let (side, spell, duration_ns) = {\n"
        "                let state = &fight.dots[dot];\n"
        "                (state.side, state.spell, state.tick_period.checked_mul(i64::from(state.remaining_ticks))\n"
        "                    .expect(\"Entangling Roots duration overflow\"))\n"
        "            };\n"
        "            let target_index = side.target_position()\n"
        "                .expect(\"Entangling Roots DoT must target an enemy\") as u32;\n"
        "            let rank_spell_id = fight.spells[spell].id.spell_id;\n"
        "            let action = format!(\"spell:{}\", rank_spell_id);\n"
        "            let expires_at_ns = fight.now.checked_add(duration_ns)\n"
        "                .expect(\"Entangling Roots expiry overflow\");\n"
        "            crate::core::fight::world_bridge::record_control_state(\n"
        "                fight.now, true, Some(expires_at_ns),\n"
        "                action, rank_spell_id, target_index, format!(\"{:?}\", side),\n"
        "            );\n"
        "        }",
        "GAIN",
    ),
    (
        "        if behavior == DruidSpell::InsectSwarm {\n"
        "            let side = fight.dots[dot].side;\n"
        "            insect_swarm::on_dot_expire(fight, fight.agent.insect_swarm_debuff, side);\n"
        "        }",
        "        if behavior == DruidSpell::InsectSwarm {\n"
        "            let side = fight.dots[dot].side;\n"
        "            insect_swarm::on_dot_expire(fight, fight.agent.insect_swarm_debuff, side);\n"
        "        }\n"
        "        if behavior == DruidSpell::EntanglingRoots {\n"
        "            let (side, spell) = {\n"
        "                let state = &fight.dots[dot];\n"
        "                (state.side, state.spell)\n"
        "            };\n"
        "            let target_index = side.target_position()\n"
        "                .expect(\"Entangling Roots DoT must target an enemy\") as u32;\n"
        "            let rank_spell_id = fight.spells[spell].id.spell_id;\n"
        "            let action = format!(\"spell:{}\", rank_spell_id);\n"
        "            crate::core::fight::world_bridge::record_control_state(\n"
        "                fight.now, false, None,\n"
        "                action, rank_spell_id, target_index, format!(\"{:?}\", side),\n"
        "            );\n"
        "        }",
        "EXPIRE",
    ),
]

WORLD_BRIDGE_PATCHES = [
    (
        "}\n\nstruct Bridge {",
        "}\n\n#[derive(Clone, Serialize)]\n"
        "struct ControlEvent {\n"
        "    event_id: String,\n"
        "    event_kind: String,\n"
        "    native_time_ns: i64,\n"
        "    control_id: String,\n"
        "    landed: Option<bool>,\n"
        "    expires_at_ns: Option<i64>,\n"
        "    source_action_id: String,\n"
        "    source_rank_spell_id: i32,\n"
        "    native_target_index: u32,\n"
        "    native_target_unit_index: u32,\n"
        "    native_target_label: String,\n"
        "}\n\nstruct Bridge {",
        "EVENT_TYPE",
    ),
    (
        "    pending: Vec<DamageEvent>,",
        "    pending: Vec<DamageEvent>,\n"
        "    control_event_ordinal: u64,\n"
        "    pending_controls: Vec<ControlEvent>,\n"
        "    root_expires_at_ns: Option<i64>,",
        "STATE",
    ),
    (
        "        source_hash: source_hash.to_owned(), event_ordinal: 0,\n"
        "        pending: Vec::new(),",
        "        source_hash: source_hash.to_owned(), event_ordinal: 0,\n"
        "        pending: Vec::new(), control_event_ordinal: 0,\n"
        "        pending_controls: Vec::new(), root_expires_at_ns: None,",
        "INIT",
    ),
    (
        "        assert!(bridge.pending.is_empty(), \"RUST_WORLD_UNFLUSHED_EVENTS\");",
        "        assert!(bridge.pending.is_empty(), \"RUST_WORLD_UNFLUSHED_EVENTS\");\n"
        "        assert!(bridge.pending_controls.is_empty(), \"RUST_WORLD_UNFLUSHED_CONTROLS\");",
        "ITERATION_PENDING",
    ),
    (
        "        bridge.event_ordinal = 0;",
        "        bridge.event_ordinal = 0;\n"
        "        bridge.control_event_ordinal = 0;\n"
        "        bridge.root_expires_at_ns = None;",
        "ITERATION_ORDINAL",
    ),
    (
        "        if !bridge.pending.is_empty() {\n"
        "            return Err(\"RUST_WORLD_UNACKNOWLEDGED_DAMAGE\");\n"
        "        }",
        "        if !bridge.pending.is_empty() {\n"
        "            return Err(\"RUST_WORLD_UNACKNOWLEDGED_DAMAGE\");\n"
        "        }\n"
        "        if !bridge.pending_controls.is_empty() {\n"
        "            return Err(\"RUST_WORLD_UNACKNOWLEDGED_CONTROLS\");\n"
        "        }",
        "NEXT_TARGET_PENDING",
    ),
    (
        "        bridge.last_health = None; // new world target, not a healed old one",
        "        bridge.last_health = None; // new world target, not a healed old one\n"
        "        bridge.root_expires_at_ns = None;",
        "NEXT_TARGET_ROOT_RESET",
    ),
    (
        "        bridge.sequence > 0 && bridge.last_health == Some(0.0)\n"
        "            && bridge.previous_ack_id.len() == 64 && bridge.pending.is_empty()",
        "        bridge.sequence > 0 && bridge.last_health == Some(0.0)\n"
        "            && bridge.previous_ack_id.len() == 64 && bridge.pending.is_empty()\n"
        "            && bridge.pending_controls.is_empty()",
        "LETHAL_PENDING_CONTROLS",
    ),
    (
        "    let last = BRIDGE.with(|state| state.borrow().as_ref()\n"
        "        .expect(\"RUST_WORLD_NOT_STARTED\").last_tick_ns);\n"
        "    if acknowledged_lethal() {",
        "    let (last, pending_controls) = BRIDGE.with(|state| {\n"
        "        let state = state.borrow();\n"
        "        let bridge = state.as_ref().expect(\"RUST_WORLD_NOT_STARTED\");\n"
        "        (bridge.last_tick_ns, !bridge.pending_controls.is_empty())\n"
        "    });\n"
        "    if acknowledged_lethal() {",
        "FINISH_PENDING_CONTROL_STATE",
    ),
    (
        "    } else {\n"
        "        let clock = ((duration_ns + 999_999) / 1_000_000) * 1_000_000;\n"
        "        let clock = clock.max(last + 1_000_000);\n"
        "        let _ = exchange(clock, duration_ns, cumulative_damage);\n"
        "    }\n"
        "    BRIDGE.with(|state| {",
        "    } else if pending_controls && duration_ns == last {\n"
        "        let _ = exchange(last, duration_ns, cumulative_damage);\n"
        "    } else {\n"
        "        let clock = ((duration_ns + 999_999) / 1_000_000) * 1_000_000;\n"
        "        let clock = clock.max(last + 1_000_000);\n"
        "        let _ = exchange(clock, duration_ns, cumulative_damage);\n"
        "    }\n"
        "    BRIDGE.with(|state| {",
        "FINISH_SAME_CLOCK_CONTROL",
    ),
    (
        "        assert!(bridge.pending.is_empty(), \"RUST_WORLD_FINISH_UNFLUSHED\");",
        "        assert!(bridge.pending.is_empty(), \"RUST_WORLD_FINISH_UNFLUSHED\");\n"
        "        assert!(bridge.pending_controls.is_empty(), \"RUST_WORLD_FINISH_UNFLUSHED_CONTROLS\");",
        "FINISH_PENDING_ASSERT",
    ),
    (
        "        let boundary = if bridge.next_tick_ns == i64::MAX {\n"
        "            if next_native_ns < 0 || next_native_ns > end_ns {\n"
        "                return None;\n"
        "            }\n"
        "            (next_native_ns / 1_000_000) * 1_000_000\n"
        "        } else {\n"
        "            bridge.next_tick_ns\n"
        "        };\n"
        "        (boundary >= 0 && boundary > bridge.last_tick_ns\n"
        "            && boundary <= next_native_ns && boundary <= end_ns)\n"
        "            .then_some(boundary)",
        "        let pending_control_time = bridge.pending_controls.iter()\n"
        "            .map(|event| event.native_time_ns).min();\n"
        "        let boundary = if let Some(control_time) = pending_control_time {\n"
        "            if control_time < bridge.last_tick_ns {\n"
        "                panic!(\"RUST_WORLD_CONTROL_EVENT_BEFORE_LAST_ACK\");\n"
        "            }\n"
        "            if control_time <= next_native_ns { control_time } else { return None; }\n"
        "        } else if bridge.next_tick_ns == i64::MAX {\n"
        "            if next_native_ns < 0 || next_native_ns > end_ns {\n"
        "                return None;\n"
        "            }\n"
        "            (next_native_ns / 1_000_000) * 1_000_000\n"
        "        } else {\n"
        "            bridge.next_tick_ns\n"
        "        };\n"
        "        let same_clock_control = pending_control_time.is_some()\n"
        "            && boundary == bridge.last_tick_ns;\n"
        "        (boundary >= 0 && (boundary > bridge.last_tick_ns || same_clock_control)\n"
        "            && boundary <= next_native_ns && boundary <= end_ns)\n"
        "            .then_some(boundary)",
        "DUE_CONTROL_BOUNDARY",
    ),
    (
        "    assert!(clock_ns > bridge.last_tick_ns && clock_ns >= 0,\n"
        "        \"RUST_WORLD_CLOCK_NOT_MONOTONIC\");",
        "    assert!(clock_ns >= 0 && (clock_ns > bridge.last_tick_ns\n"
        "        || (!bridge.pending_controls.is_empty() && clock_ns == bridge.last_tick_ns)),\n"
        "        \"RUST_WORLD_CLOCK_NOT_MONOTONIC\");",
        "EXCHANGE_SAME_CLOCK",
    ),
    (
        "            event_ordinal: 9, pending: Vec::new(),",
        "            event_ordinal: 9, pending: Vec::new(), control_event_ordinal: 0, pending_controls: Vec::new(), root_expires_at_ns: None,",
        "TEST_INIT_9",
    ),
    (
        "            event_ordinal: 3, pending: Vec::new(),",
        "            event_ordinal: 3, pending: Vec::new(), control_event_ordinal: 0, pending_controls: Vec::new(), root_expires_at_ns: None,",
        "TEST_INIT_3",
    ),
    (
        "            event_ordinal: 1, pending: Vec::new(),",
        "            event_ordinal: 1, pending: Vec::new(), control_event_ordinal: 0, pending_controls: Vec::new(), root_expires_at_ns: None,",
        "TEST_INIT_1",
    ),
    (
        "fn send(value: &Value) {",
        "fn record_control_event(event_kind: &str, time_ns: i64, landed: Option<bool>,\n"
        "    expires_at_ns: Option<i64>, action: String, rank_spell_id: i32,\n"
        "    target_index: u32, target_label: String) {\n"
        "    if !enabled() { return; }\n"
        "    assert!(time_ns >= 0, \"RUST_WORLD_CONTROL_TIME_INVALID\");\n"
        "    assert!(rank_spell_id > 0, \"RUST_WORLD_CONTROL_RANK_INVALID\");\n"
        "    assert!(target_index == 0 && target_label == \"Target\", \"RUST_WORLD_CONTROL_TARGET_INVALID\");\n"
        "    match event_kind {\n"
        "        \"attempt\" => assert!(landed.is_some() && expires_at_ns.is_none(), \"RUST_WORLD_CONTROL_ATTEMPT_INVALID\"),\n"
        "        \"apply\" => assert!(landed == Some(true) && expires_at_ns.is_some_and(|x| x > time_ns), \"RUST_WORLD_CONTROL_APPLY_INVALID\"),\n"
        "        \"expire\" => assert!(landed.is_none() && expires_at_ns.is_none(), \"RUST_WORLD_CONTROL_EXPIRE_INVALID\"),\n"
        "        _ => panic!(\"RUST_WORLD_CONTROL_KIND_INVALID\"),\n"
        "    }\n"
        "    BRIDGE.with(|state| {\n"
        "        let mut state = state.borrow_mut();\n"
        "        let bridge = state.as_mut().expect(\"RUST_WORLD_NOT_STARTED\");\n"
        "        bridge.control_event_ordinal += 1;\n"
        "        if event_kind == \"apply\" { bridge.root_expires_at_ns = expires_at_ns; }\n"
        "        if event_kind == \"expire\" { bridge.root_expires_at_ns = None; }\n"
        "        bridge.pending_controls.push(ControlEvent {\n"
        "            event_id: format!(\"native-control-{}\", bridge.control_event_ordinal),\n"
        "            event_kind: event_kind.to_owned(), native_time_ns: time_ns,\n"
        "            control_id: \"root\".to_owned(), landed, expires_at_ns,\n"
        "            source_action_id: action, source_rank_spell_id: rank_spell_id,\n"
        "            native_target_index: target_index, native_target_unit_index: target_index,\n"
        "            native_target_label: target_label,\n"
        "        });\n"
        "    });\n"
        "}\n\n"
        "pub(crate) fn record_control_attempt(time_ns: i64, landed: bool, action: String,\n"
        "    rank_spell_id: i32, target_index: u32, target_label: String) {\n"
        "    record_control_event(\"attempt\", time_ns, Some(landed), None, action, rank_spell_id, target_index, target_label);\n"
        "}\n\n"
        "pub(crate) fn record_control_state(time_ns: i64, active: bool, expires_at_ns: Option<i64>,\n"
        "    action: String, rank_spell_id: i32, target_index: u32, target_label: String) {\n"
        "    if active {\n"
        "        record_control_event(\"apply\", time_ns, Some(true), expires_at_ns, action, rank_spell_id, target_index, target_label);\n"
        "    } else {\n"
        "        record_control_event(\"expire\", time_ns, None, None, action, rank_spell_id, target_index, target_label);\n"
        "    }\n"
        "}\n\nfn send(value: &Value) {",
        "RECORD_CONTROL",
    ),
    (
        "    let events = std::mem::take(&mut bridge.pending);\n"
        "    let event_ids: Vec<String> = events.iter().map(|event| event.event_id.clone()).collect();",
        "    let events = std::mem::take(&mut bridge.pending);\n"
        "    let event_ids: Vec<String> = events.iter().map(|event| event.event_id.clone()).collect();\n"
        "    let control_events = std::mem::take(&mut bridge.pending_controls);\n"
        "    let control_event_ids: Vec<String> = control_events.iter().map(|event| event.event_id.clone()).collect();\n"
        "    let same_clock_control_boundary = !control_events.is_empty() && clock_ns == bridge.last_tick_ns;",
        "DRAIN",
    ),
    (
        "        \"type\": \"native_rust_world_boundary_request\",\n"
        "        \"iteration_index\": bridge.iteration,\n"
        "        \"sequence\": bridge.sequence, \"native_clock_ns\": clock_ns,\n"
        "        \"native_encounter_end_ns\": duration_ns,\n"
        "        \"native_process_id\": pid, \"native_request_sha256\": bridge.source_hash,\n",
        "        \"type\": \"native_rust_world_boundary_request\",\n"
        "        \"iteration_index\": bridge.iteration,\n"
        "        \"sequence\": bridge.sequence, \"native_clock_ns\": clock_ns,\n"
        "        \"native_encounter_end_ns\": duration_ns,\n"
        "        \"native_process_id\": pid, \"native_request_sha256\": bridge.source_hash,\n"
        "        \"same_clock_control_boundary\": same_clock_control_boundary,\n",
        "SAME_CLOCK_REQUEST",
    ),
    (
        "        \"native_damage_events\": events,\n"
        "        \"native_range_receipt\": {",
        "        \"native_damage_events\": events,\n"
        "        \"native_control_events\": control_events,\n"
        "        \"native_range_receipt\": {",
        "RECEIPT",
    ),
    (
        "    let ack_before = number(&ack, \"world_target_health_before\");",
        "    let accepted_controls = ack.get(\"applied_control_event_ids\")\n"
        "        .and_then(Value::as_array).cloned().unwrap_or_default();\n"
        "    assert!(accepted_controls.len() == control_event_ids.len()\n"
        "        && accepted_controls.iter().zip(control_event_ids.iter())\n"
        "            .all(|(a,b)| a.as_str() == Some(b)),\n"
        "        \"RUST_WORLD_CONTROL_ACK_EVENTS_MISMATCH\");\n"
        "    let ack_before = number(&ack, \"world_target_health_before\");",
        "ACK",
    ),
]

ROOTS_MODULE_PATH = "src/classes/druid/spells/entangling_roots.rs"


def port_text(path: str, contents: str) -> str:
    if path == ROOTS_MODULE_PATH:
        if contents and contents != ROOTS_MODULE:
            raise ValueError("NATIVE_ROOTS_CONTROL_MODULE_SOURCE_DRIFT")
        return ROOTS_MODULE
    patches = {
        "src/classes/druid/agent.rs": AGENT_PATCHES,
        "src/core/fight/world_bridge.rs": WORLD_BRIDGE_PATCHES,
    }
    if path in patches:
        for old, new, label in patches[path]:
            contents = replace_once(contents, old, new, label)
        return contents
    if path == "src/classes/druid/spells.rs":
        return replace_once(
            contents,
            "pub(crate) mod bear;\n",
            "pub(crate) mod bear;\npub(crate) mod entangling_roots;\n",
            "MODULE",
        )
    raise ValueError("unsupported port target " + path)


PATHS = [
    "src/classes/druid/spells.rs",
    "src/classes/druid/spells/entangling_roots.rs",
    "src/classes/druid/agent.rs",
    "src/core/fight/world_bridge.rs",
]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        raise SystemExit("usage: port_native_entangling_roots_control.py RUST_ENGINE_ROOT")
    root = Path(argv[1])
    original = {
        path: (root / path).read_text() if (root / path).exists() else ""
        for path in PATHS
    }
    result = {path: port_text(path, original[path]) for path in PATHS}
    for path, value in result.items():
        if value != original[path]:
            destination = root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(value)
    print("RUST_FOREVER_ROOTS_CONTROL_SOURCE_PORT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
