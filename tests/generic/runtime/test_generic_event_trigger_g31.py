from pathlib import Path

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.v2.generic_backend import build_partial_generic_records


def test_g31_thorns_compiles_to_generic_source_backed_event_trigger():
    low = build_game_ir_slice(class_key="Druid", level=23)
    assert low.triggers == ()

    ir = build_game_ir_slice(class_key="Druid", level=25)
    assert ir.schema_version == 16
    assert len(ir.triggers) == 1
    trigger = ir.triggers[0]
    assert trigger.id == "thorns:1075:reactive"
    assert trigger.event_kind == "damage_taken"
    assert trigger.event_probability_field == "hit_chance"
    assert trigger.active_by_default is True
    assert trigger.metadata["g31_scope"] == "generic_event_trigger_damage"
    effect = trigger.effects[0]
    assert effect.school == "Nature"
    assert effect.base_min == pytest.approx(11.0)
    assert effect.base_max == pytest.approx(11.0)
    maintenance = next(x for x in ir.policies[0].maintenance if x["family_key"] == "thorns")
    assert maintenance["execution_status"] == "executable_generic_event_trigger_runtime"
    assert maintenance["trigger_id"] == trigger.id


def test_g31_incoming_hit_fires_trigger_and_applies_real_damage_without_class_dispatch():
    ir = build_game_ir_slice(class_key="Druid", level=25)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.stats["armor"] = 0.0
    target = TargetState.with_health("g31-runtime", 100.0)
    runtime = CombatRuntime(actor=actor, target=target, triggers=ir.triggers)
    runtime.resolve_incoming_attack(ir.incoming_attacks[0], mitigation_rules=ir.mitigation_rules)
    result = runtime.result()

    assert target.health == pytest.approx(89.0)
    fired = [e for e in result.events if e.kind == "TriggerFired"]
    damage = [e for e in result.events if e.kind == "Damage" and e.payload.get("trigger_id") == ir.triggers[0].id]
    assert len(fired) == 1
    assert len(damage) == 1
    assert damage[0].payload["amount"] == pytest.approx(11.0)
    assert damage[0].payload["resolution"] == "expected_value_event_trigger"

    runtime_source = Path("src/game/runtime/simulator.py").read_text(encoding="utf-8").lower()
    assert "druid" not in runtime_source
    assert "thorns" not in runtime_source


def test_g31_trigger_changes_real_generic_timing_probe_and_capability():
    record = build_partial_generic_records(class_names=("Druid",), selected_level=25)[0]
    assert record.capability["event_trigger_runtime"] is True
    assert record.capability["event_trigger_runtime_scope"] == "generic_runtime_event_to_damage_effect"
    assert "event_trigger_runtime" not in record.unsupported_mechanics
    assert "incoming_hit_trigger_runtime" not in record.unsupported_mechanics

    probe = record.provenance["event_trigger_damage_probe"]
    assert probe["status"] == "executed"
    assert probe["trigger_id"] == "thorns:1075:reactive"
    assert probe["trigger_count"] == 1
    assert probe["trigger_damage"] == pytest.approx(11.0)
    assert probe["baseline_seconds_per_mob"] == pytest.approx(3.5)
    assert probe["trigger_seconds_per_mob"] == pytest.approx(1.5)
    assert probe["improvement_seconds_per_mob"] == pytest.approx(2.0)
    assert probe["legacy_fallback"] is False


def test_g31_listener_surfaces_executable_trigger_and_timing_delta():
    from src.listener import DECISIONS_HTML

    assert "Generic event trigger" in DECISIONS_HTML
    assert "function genericEventTriggerSummary(r)" in DECISIONS_HTML
    assert "eventTriggerHtml" in DECISIONS_HTML
