#!/usr/bin/env python3
"""Port native Entangling Roots control events into the selected Rust engine.

The Rust DoT remains the authority for hit/miss and duration.  This port exports
attempt, gain, and expiry events through the existing native world bridge so the
2D gsim runtime can stop and resume the real target's approach.  Damage-break,
rank-specific control duration, and multi-target cap semantics remain follow-up
source-capture work; this slice deliberately tests an otherwise-undamaged target.
"""
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"SOURCE_DRIFT:{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def replace_all_exact(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count == 0 and text.count(new) == expected:
        return text
    if count != expected:
        raise SystemExit(f"SOURCE_DRIFT:{label}: expected {expected} anchors, found {count}")
    return text.replace(old, new)


def port_agent(path: Path) -> None:
    text = path.read_text()
    text = replace_once(
        text,
        "DruidSpell::EntanglingRoots => insect_swarm::apply(fight, spell, target),",
        """DruidSpell::EntanglingRoots => {
                let result = fight.calc_outcome(
                    spell,
                    target,
                    crate::core::fight::Outcome::MagicHit,
                );
                crate::core::fight::world_bridge::record_control_attempt(
                    fight.now,
                    result.landed(),
                );
                if result.landed() {
                    let dot = fight.spells[spell]
                        .dot
                        .expect("Entangling Roots has a dot");
                    fight.apply_dot(fight.dot_on(dot, target));
                }
                fight.deal_damage(spell, result, false);
            }""",
        "druid_roots_native_apply",
    )
    text = replace_once(
        text,
        """fn on_dot_gain(fight: &mut Fight<Self>, dot: DotId, behavior: DruidSpell) {
        if behavior == DruidSpell::InsectSwarm {
            let side = fight.dots[dot].side;
            insect_swarm::on_dot_gain(fight, fight.agent.insect_swarm_debuff, side);
        }
    }""",
        """fn on_dot_gain(fight: &mut Fight<Self>, dot: DotId, behavior: DruidSpell) {
        if behavior == DruidSpell::InsectSwarm {
            let side = fight.dots[dot].side;
            insect_swarm::on_dot_gain(fight, fight.agent.insect_swarm_debuff, side);
        }
        if behavior == DruidSpell::EntanglingRoots {
            let aura = fight.dots[dot].aura;
            let duration_ns = fight.aura(aura).remaining(fight.now);
            crate::core::fight::world_bridge::record_control_gain(fight.now, duration_ns);
        }
    }""",
        "druid_roots_native_gain",
    )
    text = replace_once(
        text,
        """fn on_dot_expire(fight: &mut Fight<Self>, dot: DotId, behavior: DruidSpell) {
        if behavior == DruidSpell::Heal {
            if let Some(bloom) = fight.agent.bloom.clone() {
                bloom.on_dot_expire(fight, dot);
            }
        }
        if behavior == DruidSpell::InsectSwarm {
            let side = fight.dots[dot].side;
            insect_swarm::on_dot_expire(fight, fight.agent.insect_swarm_debuff, side);
        }
        if behavior == DruidSpell::EntanglingRoots {
            crate::core::fight::world_bridge::record_control_expire(fight.now);
        }
    }""",
        """fn on_dot_expire(fight: &mut Fight<Self>, dot: DotId, behavior: DruidSpell) {
        if behavior == DruidSpell::Heal {
            let side = fight.dots[dot].side;
            fight.deactivate_aura(fight.agent.rejuvenation[side]);
        }
        if behavior == DruidSpell::InsectSwarm {
            let side = fight.dots[dot].side;
            insect_swarm::on_dot_expire(fight, fight.agent.insect_swarm_debuff, side);
        }
        if behavior == DruidSpell::EntanglingRoots {
            crate::core::fight::world_bridge::record_control_expire(fight.now);
        }
    }""",
        "druid_roots_native_expire",
    )
    path.write_text(text)


def port_world_bridge(path: Path) -> None:
    text = path.read_text()
    text = replace_once(
        text,
        "struct Bridge {",
        """#[derive(Clone, Serialize)]
struct ControlEvent {
    event_id: String,
    native_time_ns: i64,
    event_kind: String,
    control_id: String,
    source_action_id: String,
    landed: bool,
    duration_ns: i64,
}

struct Bridge {""",
        "world_bridge_control_event_type",
    )
    text = replace_once(
        text,
        "    event_ordinal: u64,\n    pending: Vec<DamageEvent>,\n",
        "    event_ordinal: u64,\n    pending: Vec<DamageEvent>,\n    control_ordinal: u64,\n    pending_controls: Vec<ControlEvent>,\n",
        "world_bridge_control_event_state",
    )
    text = replace_all_exact(
        text,
        "pending: Vec::new(),",
        "pending: Vec::new(),\n            control_ordinal: 0,\n            pending_controls: Vec::new(),",
        4,
        "world_bridge_control_event_initializers",
    )
    text = replace_once(
        text,
        'assert!(bridge.pending.is_empty(), "RUST_WORLD_UNFLUSHED_EVENTS");',
        'assert!(bridge.pending.is_empty() && bridge.pending_controls.is_empty(), "RUST_WORLD_UNFLUSHED_EVENTS");',
        "world_bridge_iteration_pending_guard",
    )
    text = replace_once(
        text,
        "bridge.event_ordinal = 0;",
        "bridge.event_ordinal = 0;\n        bridge.control_ordinal = 0;",
        "world_bridge_iteration_control_ordinal",
    )
    text = replace_once(
        text,
        """if !bridge.pending.is_empty() {
            return Err("RUST_WORLD_UNACKNOWLEDGED_DAMAGE");
        }""",
        """if !bridge.pending.is_empty() || !bridge.pending_controls.is_empty() {
            return Err("RUST_WORLD_UNACKNOWLEDGED_DAMAGE");
        }""",
        "world_bridge_target_handoff_control_guard",
    )
    text = replace_once(
        text,
        """let boundary = if bridge.next_tick_ns == i64::MAX {
            if next_native_ns < 0 || next_native_ns > end_ns {
                return None;
            }
            (next_native_ns / 1_000_000) * 1_000_000
        } else {
            bridge.next_tick_ns
        };""",
        """let scheduled_boundary = if bridge.next_tick_ns == i64::MAX {
            if next_native_ns < 0 || next_native_ns > end_ns {
                return None;
            }
            (next_native_ns / 1_000_000) * 1_000_000
        } else {
            bridge.next_tick_ns
        };
        // A control event can be recorded by a native callback at the same
        // timestamp as the last world tick.  Flush it at the next representable
        // millisecond, never later than 1 ms after its native timestamp.
        let next_world_ms = ((bridge.last_tick_ns / 1_000_000) + 1).max(0) * 1_000_000;
        let control_boundary = bridge
            .pending_controls
            .iter()
            .map(|event| {
                let rounded = event.native_time_ns.saturating_add(999_999) / 1_000_000 * 1_000_000;
                rounded.max(next_world_ms)
            })
            .min();
        let boundary = control_boundary.map_or(scheduled_boundary, |control| control.min(scheduled_boundary));""",
        "world_bridge_control_event_boundary",
    )
    text = replace_once(
        text,
        """fn send(value: &Value) {""",
        """fn record_control_event(time_ns: i64, event_kind: &str, landed: bool, duration_ns: i64) {
    if !enabled() {
        return;
    }
    assert!(time_ns >= 0 && duration_ns >= 0, "RUST_WORLD_CONTROL_INVALID");
    match event_kind {
        "attempt" => assert!(duration_ns == 0, "RUST_WORLD_CONTROL_ATTEMPT_DURATION"),
        "gain" => assert!(landed && duration_ns > 0, "RUST_WORLD_CONTROL_GAIN_DURATION"),
        "expire" => assert!(landed && duration_ns == 0, "RUST_WORLD_CONTROL_EXPIRE_DURATION"),
        _ => panic!("RUST_WORLD_CONTROL_KIND_INVALID"),
    }
    BRIDGE.with(|state| {
        let mut state = state.borrow_mut();
        let bridge = state.as_mut().expect("RUST_WORLD_NOT_STARTED");
        assert!(time_ns >= bridge.last_tick_ns, "RUST_WORLD_CONTROL_TIME_REWOUND");
        bridge.control_ordinal += 1;
        bridge.pending_controls.push(ControlEvent {
            event_id: format!("native-control-{}", bridge.control_ordinal),
            native_time_ns: time_ns,
            event_kind: event_kind.to_owned(),
            control_id: "root".to_owned(),
            source_action_id: "druid.entangling_roots".to_owned(),
            landed,
            duration_ns,
        });
    });
}

pub(crate) fn record_control_attempt(time_ns: i64, landed: bool) {
    record_control_event(time_ns, "attempt", landed, 0);
}

pub(crate) fn record_control_gain(time_ns: i64, duration_ns: i64) {
    record_control_event(time_ns, "gain", true, duration_ns);
}

pub(crate) fn record_control_expire(time_ns: i64) {
    record_control_event(time_ns, "expire", true, 0);
}

fn send(value: &Value) {""",
        "world_bridge_control_event_recorders",
    )
    text = replace_once(
        text,
        """let events = std::mem::take(&mut bridge.pending);
        let event_ids: Vec<String> = events.iter().map(|event| event.event_id.clone()).collect();
        let control_events = std::mem::take(&mut bridge.pending_controls);
        let control_event_ids: Vec<String> = control_events
            .iter()
            .map(|event| event.event_id.clone())
            .collect();
        let pid = std::process::id();""",
        """let events = std::mem::take(&mut bridge.pending);
        let event_ids: Vec<String> = events.iter().map(|event| event.event_id.clone()).collect();
        let control_events = std::mem::take(&mut bridge.pending_controls);
        let control_event_ids: Vec<String> = control_events
            .iter()
            .map(|event| event.event_id.clone())
            .collect();
        let pid = std::process::id();""",
        "world_bridge_exchange_take_controls",
    )
    text = replace_once(
        text,
        '"native_damage_events": events,',
        '"native_damage_events": events,\n            "native_control_events": control_events,',
        "world_bridge_receipt_controls",
    )
    text = replace_once(
        text,
        """assert!(accepted.len() == event_ids.len()
        && accepted.iter().zip(event_ids.iter()).all(|(a,b)| a.as_str() == Some(b)),
        "RUST_WORLD_DAMAGE_ACK_EVENTS_MISMATCH");""",
        """assert!(accepted.len() == event_ids.len()
            && accepted.iter().zip(event_ids.iter()).all(|(a, b)| a.as_str() == Some(b)),
            "RUST_WORLD_DAMAGE_ACK_EVENTS_MISMATCH");
        let accepted_controls = ack["applied_control_event_ids"]
            .as_array()
            .expect("RUST_WORLD_CONTROL_ACK_IDS_MISSING");
        assert!(
            accepted_controls.len() == control_event_ids.len()
                && accepted_controls
                    .iter()
                    .zip(control_event_ids.iter())
                    .all(|(a, b)| a.as_str() == Some(b)),
            "RUST_WORLD_CONTROL_ACK_EVENTS_MISMATCH"
        );""",
        "world_bridge_control_ack_validation",
    )
    text = replace_once(
        text,
        """bridge.sequence > 0 && bridge.last_health == Some(0.0)
            && bridge.previous_ack_id.len() == 64 && bridge.pending.is_empty()""",
        """bridge.sequence > 0 && bridge.last_health == Some(0.0)
            && bridge.previous_ack_id.len() == 64 && bridge.pending.is_empty()
            && bridge.pending_controls.is_empty()""",
        "world_bridge_lethal_pending_controls",
    )
    text = replace_once(
        text,
        'assert!(bridge.pending.is_empty(), "RUST_WORLD_FINISH_UNFLUSHED");',
        'assert!(bridge.pending.is_empty() && bridge.pending_controls.is_empty(), "RUST_WORLD_FINISH_UNFLUSHED");',
        "world_bridge_finish_pending_controls",
    )
    path.write_text(text)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: port_native_entangling_roots_control.py RUST_ENGINE_ROOT")
    root = Path(sys.argv[1])
    agent = root / "src/classes/druid/agent.rs"
    bridge = root / "src/core/fight/world_bridge.rs"
    if not agent.is_file() or not bridge.is_file():
        raise SystemExit("RUST_ENGINE_SOURCE_FILES_MISSING")
    port_agent(agent)
    port_world_bridge(bridge)
    print("native_entangling_roots_control_port=APPLIED")


if __name__ == "__main__":
    main()
