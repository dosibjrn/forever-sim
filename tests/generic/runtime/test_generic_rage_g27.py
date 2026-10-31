from __future__ import annotations

from pathlib import Path

import pytest

from src.game.model import (
    ActionDefinition, ActorDefinition, AutoAttackDamageSource, AutoAttackDefinition,
    DamageEffect, ModeDefinition, ModeResourceRule, ResourceCost, ResourceDefinition,
    ResourceEventGainRule,
)
from src.game.runtime import ActorState, CombatRuntime, TargetState, action_eligibility


def _rage_runtime():
    actor_def = ActorDefinition(id="generic-rage-proof", actor_type="player", metadata={"level": 20})
    rage = ResourceDefinition(
        id="rage", name="Rage", owner_actor_id=actor_def.id,
        initial_amount=0.0, capacity=100.0, active_by_default=False,
        event_gain_rules=(
            ResourceEventGainRule(
                id="white-damage-to-rage", event_kind="damage_dealt", event_value_field="amount",
                multiplier=0.25, required_mode_id="bear", filters={"auto_attack": True},
                provenance=({"authority": "g27_generic_mechanics_probe"},),
            ),
            ResourceEventGainRule(
                id="incoming-damage-to-rage", event_kind="damage_taken", event_value_field="amount",
                multiplier=0.5, required_mode_id="bear",
                provenance=({"authority": "g27_generic_mechanics_probe"},),
            ),
        ),
    )
    modes = (
        ModeDefinition(
            id="caster", label="Caster", initial=False, enabled_action_ids=(),
            resource_rules=(ModeResourceRule(resource_id="rage", active=False),),
        ),
        ModeDefinition(
            id="bear", label="Bear-shaped proof", initial=True, enabled_action_ids=None,
            resource_rules=(ModeResourceRule(resource_id="rage", active=True),),
        ),
    )
    actor = ActorState.from_ir(actor_def, (rage,), modes)
    target = TargetState.with_health("target", 1000.0)
    auto = AutoAttackDefinition(
        id="auto:generic-melee", name="Generic melee", owner_actor_id=actor_def.id,
        attack_type="melee", swing_time_s=2.0, school="physical",
        damage_source=AutoAttackDamageSource(kind="flat", flat_dps=10.0, attack_power_stat_id=None),
        required_mode_id="bear", hit_chance=1.0, crit_chance_on_landed_hit=0.0,
    )
    strike = ActionDefinition(
        id="rage-strike", family_key="rage_strike", name="Rage strike", owner_actor_id=actor_def.id,
        requirements=({"kind": "mode_is", "value": "bear"},),
        costs=(ResourceCost(resource_id="rage", amount=10.0),),
        cast_time_s=0.0, gcd_s=1.5, cooldown_s=0.0,
        effects=(DamageEffect(
            effect_type="damage", school="physical", target="enemy",
            base_min=30.0, base_max=30.0,
        ),),
        provenance=({"authority": "g27_generic_mechanics_probe"},),
    )
    runtime = CombatRuntime(actor=actor, target=target, auto_attacks=(auto,))
    return actor, target, runtime, strike


def test_g27_event_gain_rule_is_generic_ir_and_serializes():
    actor, _, _, _ = _rage_runtime()
    rage = actor.resource_definitions["rage"]
    assert rage.capacity == pytest.approx(100.0)
    rules = rage.event_gain_rules
    assert [r.event_kind for r in rules] == ["damage_dealt", "damage_taken"]
    payload = rage.as_dict()
    assert payload["event_gain_rules"][0]["filters"] == {"auto_attack": True}
    assert payload["event_gain_rules"][0]["required_mode_id"] == "bear"


def test_g27_autoattack_damage_generates_rage_and_unlocks_spender():
    actor, target, runtime, strike = _rage_runtime()
    assert actor.resource_amount("rage") == pytest.approx(0.0)
    assert action_eligibility(action=strike, actor=actor, target=target).eligible is False

    runtime.advance_to(2.0)
    assert actor.resource_amount("rage") == pytest.approx(5.0)
    blocked = action_eligibility(action=strike, actor=actor, target=target)
    assert blocked.eligible is False
    assert "insufficient rage" in str(blocked.reason)

    runtime.advance_to(4.0)
    assert actor.resource_amount("rage") == pytest.approx(10.0)
    assert action_eligibility(action=strike, actor=actor, target=target).eligible is True
    runtime.schedule_action(strike)
    assert actor.resource_amount("rage") == pytest.approx(0.0)
    result = runtime.result()
    gains = [e for e in result.events if e.kind == "ResourceEventGain" and e.payload.get("resource_id") == "rage"]
    assert len(gains) >= 2
    assert gains[0].payload["gained"] == pytest.approx(5.0)


def test_g27_event_gain_caps_and_damage_taken_hook_is_ready_for_g28():
    actor, _, runtime, _ = _rage_runtime()
    queued = runtime.emit_resource_event("damage_taken", amount=500.0, source="incoming_probe")
    assert queued == 1
    assert actor.resource_amount("rage") == pytest.approx(100.0)
    gain = next(e for e in runtime.result().events if e.kind == "ResourceEventGain" and e.payload.get("event_kind") == "damage_taken")
    assert gain.payload["requested_gain"] == pytest.approx(250.0)
    assert gain.payload["gained"] == pytest.approx(100.0)
    assert gain.payload["capped"] is True


def test_g27_mode_activation_controls_event_resource_gain_without_class_dispatch():
    actor, _, runtime, _ = _rage_runtime()
    actor.transition_mode("caster")
    assert actor.resource_is_active("rage") is False
    assert runtime.emit_resource_event("damage_taken", amount=40.0) == 0
    assert actor.resource_amount("rage") == pytest.approx(0.0)

    runtime_source = Path("src/game/runtime/simulator.py").read_text(encoding="utf-8").lower()
    state_source = Path("src/game/runtime/state.py").read_text(encoding="utf-8").lower()
    assert "druid" not in runtime_source
    assert "bear" not in runtime_source
    assert "warrior" not in runtime_source
    assert "druid" not in state_source
    assert "bear" not in state_source


def test_g27_damage_event_gain_is_filtered_by_payload():
    actor, target, _runtime, _ = _rage_runtime()
    runtime = CombatRuntime(actor=actor, target=target, auto_attacks=())
    # A normal action Damage payload is not an auto attack, so the white-damage rule must not fire.
    strike_free = ActionDefinition(
        id="free-hit", family_key="free_hit", name="Free hit", owner_actor_id=actor.id,
        requirements=(), costs=(), cast_time_s=0.0, gcd_s=0.0, cooldown_s=0.0,
        effects=(DamageEffect(effect_type="damage", school="physical", target="enemy", base_min=40.0, base_max=40.0),),
        provenance=(),
    )
    runtime.schedule_action(strike_free)
    runtime.run_until_idle()
    assert actor.resource_amount("rage") == pytest.approx(0.0)
    assert target.health < target.max_health


def test_g27_druid_ir_publishes_source_backed_inactive_rage_rule_and_backend_capability():
    from src.game.data.forever import build_game_ir_slice
    from src.v2.generic_backend import build_partial_generic_records

    ir = build_game_ir_slice(class_key="Druid", level=20)
    assert ir.schema_version == 16
    rage = next(r for r in ir.resources if r.id == "rage")
    assert rage.capacity == pytest.approx(100.0)
    assert rage.initial_amount == pytest.approx(0.0)
    assert rage.active_by_default is False
    assert rage.metadata["activation"] == "bear_mode_managed_by_generic_mode_runtime"
    rule = rage.event_gain_rules[0]
    assert rule.event_kind == "damage_taken_rage_basis"
    assert rule.required_mode_id == "bear"
    assert rule.multiplier > 0.0
    assert rule.metadata["raw_incoming_conversion"] == "incoming_event_projection:landed_raw_damage_x_fixed_armor_fraction"

    record = build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]
    assert record.capability["event_driven_resource_gain"] is True
    assert "event_driven_resource_gain" not in record.unsupported_mechanics
    probe = record.provenance["event_resource_gain_probe"]
    assert probe["resource_id"] == "rage"
    assert probe["spender_eligible_before_gain"] is False
    assert probe["spender_eligible_after_gain"] is True
    assert probe["resource_after_gain"] == pytest.approx(20.0)
    assert probe["resource_after_spend"] == pytest.approx(5.0)
    assert probe["legacy_fallback"] is False
    from src.listener import DECISIONS_HTML
    assert "Generic event-driven Rage" in DECISIONS_HTML
    assert "function genericEventResourceSummary(r)" in DECISIONS_HTML
