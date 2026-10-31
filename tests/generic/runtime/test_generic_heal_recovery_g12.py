from __future__ import annotations

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import HealEffect, PeriodicHealEffect
from src.game.recovery import recover_actor_to_full
from src.game.runtime import ActorState, TargetState, execute_action
from src.v2.generic_backend import build_partial_generic_records


def _druid(level: int = 20):
    ir = build_game_ir_slice(class_key="Druid", level=level)
    assert ir is not None
    return ir


def test_g12_ir_publishes_health_direct_heal_and_hot_as_generic_effects():
    ir = _druid(20)
    assert ir.schema_version >= 5
    health = next(r for r in ir.resources if r.id == "health")
    assert health.capacity == pytest.approx(500.0)
    assert health.state_status == "qualified_proxy_starting_state"

    ht = next(a for a in ir.actions if a.family_key == "healing_touch")
    heal = next(e for e in ht.effects if isinstance(e, HealEffect))
    assert ht.id == "healing_touch:rank@20"
    assert sum(c.amount for c in ht.costs if c.resource_id == "mana") == pytest.approx(185.0)
    assert ht.cast_time_s == pytest.approx(3.0)
    assert (heal.base_min, heal.base_max, heal.spell_power_coefficient) == pytest.approx((376.0, 459.0, 0.857))

    rejuv = next(a for a in ir.actions if a.family_key == "rejuvenation")
    hot = next(e for e in rejuv.effects if isinstance(e, PeriodicHealEffect))
    assert rejuv.id == "rejuvenation:rank@16"
    assert hot.total_base_heal == pytest.approx(116.0)
    assert hot.duration_s == pytest.approx(12.0)
    assert hot.tick_interval_s == pytest.approx(3.0)
    assert hot.spell_power_coefficient_per_tick == pytest.approx(0.170)


def test_g12_direct_heal_executes_on_actor_resource_through_generic_runtime():
    ir = _druid(20)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    actor.resources["health"] = 100.0
    ht = next(a for a in ir.actions if a.family_key == "healing_touch")
    result = execute_action(action=ht, actor=actor, target=TargetState.with_health("recovery-context", 1.0))
    heals = [e for e in result.events if e.kind == "Heal"]
    assert len(heals) == 1
    assert heals[0].payload["amount"] == pytest.approx(417.5)
    assert heals[0].payload["restored"] == pytest.approx(400.0)
    assert actor.resource_amount("health") == pytest.approx(500.0)
    assert actor.resource_amount("mana") == pytest.approx(429.0)


def test_g12_periodic_heal_reuses_actor_aura_and_event_queue():
    ir = _druid(20)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    actor.resources["health"] = 100.0
    action = next(a for a in ir.actions if a.family_key == "rejuvenation")
    result = execute_action(action=action, actor=actor, target=TargetState.with_health("recovery-context", 1.0))
    heals = [e for e in result.events if e.kind == "Heal"]
    assert len(heals) == 4
    assert [float(e.payload["amount"]) for e in heals] == pytest.approx([29.0] * 4)
    assert sum(e.kind == "AuraApplied" for e in result.events) == 1
    assert sum(e.kind == "AuraExpired" for e in result.events) == 1
    assert actor.resource_amount("health") == pytest.approx(216.0)
    assert actor.resource_amount("mana") == pytest.approx(539.0)


def test_g12_recovery_uses_same_actor_state_and_real_heal_action_when_useful():
    ir = _druid(20)
    with_heal = ActorState.from_ir(ir.actor, ir.resources)
    with_heal.resources.update({"health": 100.0, "mana": 400.0})
    recovered = recover_actor_to_full(actor=with_heal, level=20, actions=ir.actions, start_time_s=10.0)

    without_heal = ActorState.from_ir(ir.actor, ir.resources)
    without_heal.resources.update({"health": 100.0, "mana": 400.0})
    no_heal_actions = tuple(a for a in ir.actions if a.family_key not in {"healing_touch", "rejuvenation"})
    ordinary = recover_actor_to_full(actor=without_heal, level=20, actions=no_heal_actions, start_time_s=10.0)

    assert recovered.heal_action_id == "healing_touch:rank@20"
    assert recovered.heal_casts == 1
    assert recovered.total_s < ordinary.total_s
    assert recovered.total_s == pytest.approx(10.943478260869565)
    assert {k: recovered.resources_after[k] for k in ("mana", "health")} == pytest.approx({"mana": 614.0, "health": 500.0})
    assert any(e["kind"] == "Heal" for e in recovered.heal_events)


def test_g12_active_generic_evaluation_adds_real_postcombat_mana_recovery_without_fake_hp_damage():
    record = build_partial_generic_records(class_names=["Druid"], selected_level=20)[0]
    assert record.capability["status"] == "combat_recovery_evaluation"
    assert record.capability["recovery_evaluation"] is True
    assert record.capability["direct_heal_runtime"] is True
    assert record.capability["periodic_heal_runtime"] is True
    assert record.objective["evaluation_scope"] == "combat_plus_recovery"
    naked = record.provenance["naked_evaluation"]
    assert naked["kill_seconds_per_mob"] == pytest.approx(13.5)
    assert naked["recovery_seconds_per_mob"] == pytest.approx(5.108695652173914)
    assert naked["seconds_per_mob"] == pytest.approx(18.608695652173914)
    recovery = naked["diagnostics"]["recovery"]
    assert {k: recovery["resources_before"][k] for k in ("mana", "health")} == pytest.approx({"mana": 379.0, "health": 500.0})
    assert {k: recovery["resources_after"][k] for k in ("mana", "health")} == pytest.approx({"mana": 614.0, "health": 500.0})
    assert recovery["health_missing_before"] == pytest.approx(0.0)
    assert recovery["mana_missing_before"] == pytest.approx(235.0)
    assert recovery["method"] == "water"
    assert "recovery_evaluation" not in record.unsupported_mechanics
    assert record.capability["incoming_player_damage_runtime"] is True
    assert "incoming_player_damage_runtime" not in record.unsupported_mechanics
    assert "canonical_player_health_authority" in record.unsupported_mechanics
    assert record.provenance["legacy_fallback"] is False


def test_g12_listener_surfaces_generic_heal_hot_and_recovery_without_class_dispatch():
    from src import listener
    html = listener.DECISIONS_HTML
    assert "Generic Heal / HoT runtime" in html
    assert "periodic heal" in html
    assert "recovery_seconds_per_mob" in html
    start = html.index("function genericHealingRuntimeSummary(r)")
    end = html.index("function genericTalentSummary(r)", start)
    renderer = html[start:end].lower()
    assert "druid" not in renderer
    assert "healing touch" not in renderer
    assert "rejuvenation" not in renderer
