from __future__ import annotations

from pathlib import Path

import pytest

from src.game.model import (
    ActorDefinition,
    ArmorMitigationDefinition,
    IncomingAttackDefinition,
    IncomingEventProjection,
    ResourceDefinition,
    ResourceEventGainRule,
)
from src.game.runtime import ActorState, CombatRuntime, TargetState, expected_incoming_attack


def _runtime(*, armor: float, health: float = 100.0):
    actor_def = ActorDefinition(id="player", actor_type="player", base_stats={"armor": armor}, metadata={"level": 20})
    health_res = ResourceDefinition(
        id="health", name="Health", owner_actor_id="player",
        initial_amount=health, capacity=health,
    )
    rage_res = ResourceDefinition(
        id="rage", name="Rage", owner_actor_id="player",
        initial_amount=0.0, capacity=100.0,
        event_gain_rules=(ResourceEventGainRule(
            id="rage-from-basis", event_kind="damage_taken_rage_basis",
            event_value_field="amount", multiplier=0.1,
        ),),
    )
    actor = ActorState.from_ir(actor_def, (health_res, rage_res), ())
    target = TargetState.with_health("enemy", 1000.0)
    mitigation = ArmorMitigationDefinition(
        id="classic-physical", school="physical", armor_stat_id="armor",
        armor_constant=2100.0, reduction_cap=0.75,
    )
    attack = IncomingAttackDefinition(
        id="mob-swing", name="Mob swing", source_actor_id="mob", target_actor_id="player",
        school="physical", raw_damage=100.0, hit_chance=0.8,
        health_resource_id="health", mitigation_rule_id=mitigation.id,
        event_projections=(IncomingEventProjection(
            id="forever-rage-basis", event_kind="damage_taken_rage_basis",
            source_value_field="landed_raw_damage", multiplier=0.5,
        ),),
    )
    return actor, CombatRuntime(actor=actor, target=target), mitigation, attack


def test_g28_expected_incoming_attack_executes_generic_armor_formula():
    actor, _runtime_obj, mitigation, attack = _runtime(armor=500.0)
    row = expected_incoming_attack(attack, actor=actor, mitigation_rules=(mitigation,))
    assert row["landed_raw_damage"] == pytest.approx(80.0)
    assert row["armor_reduction"] == pytest.approx(500.0 / 2600.0)
    assert row["post_mitigation_damage"] == pytest.approx(80.0 * (1.0 - 500.0 / 2600.0))
    assert row["resolution"] == "expected_value_incoming_attack"


def test_g28_real_armor_changes_health_loss_but_not_fixed_forever_rage_basis():
    low_actor, low_runtime, low_mit, attack = _runtime(armor=0.0)
    high_actor, high_runtime, high_mit, _ = _runtime(armor=1000.0)
    low = low_runtime.resolve_incoming_attack(attack, mitigation_rules=(low_mit,))
    high = high_runtime.resolve_incoming_attack(attack, mitigation_rules=(high_mit,))

    assert low["health_damage_applied"] == pytest.approx(80.0)
    assert high["health_damage_applied"] < low["health_damage_applied"]
    # Rage projection is landed pre-mitigation damage * 0.5 => 40, then * 0.1 rule => 4 Rage.
    assert low_actor.resource_amount("rage") == pytest.approx(4.0)
    assert high_actor.resource_amount("rage") == pytest.approx(4.0)
    projections = [e for e in high_runtime.result().events if e.kind == "IncomingEventProjected"]
    assert projections[0].payload["amount"] == pytest.approx(40.0)


def test_g28_survivability_clamps_health_and_emits_actor_death():
    actor, runtime, mitigation, attack = _runtime(armor=0.0, health=30.0)
    row = runtime.resolve_incoming_attack(attack, mitigation_rules=(mitigation,))
    assert row["actor_alive"] is False
    assert actor.resource_amount("health") == pytest.approx(0.0)
    assert row["health_damage_applied"] == pytest.approx(30.0)
    assert any(e.kind == "ActorDied" for e in runtime.result().events)


def test_g28_druid_ir_publishes_incoming_mitigation_and_forever_rage_projection():
    from src.game.data.forever import build_game_ir_slice

    ir = build_game_ir_slice(class_key="Druid", level=20)
    assert ir.schema_version == 16
    assert len(ir.mitigation_rules) == 1
    assert len(ir.incoming_attacks) == 1
    mitigation = ir.mitigation_rules[0]
    attack = ir.incoming_attacks[0]
    projection = attack.event_projections[0]
    assert mitigation.armor_stat_id == "armor"
    assert mitigation.armor_constant == pytest.approx(2270.0)
    assert attack.mitigation_rule_id == mitigation.id
    assert projection.event_kind == "damage_taken_rage_basis"
    assert projection.source_value_field == "landed_raw_damage"
    assert projection.multiplier == pytest.approx(0.5)
    rage = next(r for r in ir.resources if r.id == "rage")
    assert rage.metadata["incoming_damage_basis"] == "g28_incoming_event_projection"


def test_g28_backend_capability_probe_and_listener_are_native_and_class_agnostic():
    from src.listener import DECISIONS_HTML
    from src.v2.generic_backend import build_partial_generic_records

    record = build_partial_generic_records(class_names=("Druid",), selected_level=20)[0]
    assert record.capability["incoming_player_damage_runtime"] is True
    assert record.capability["armor_mitigation_runtime"] is True
    assert record.capability["survivability_state"] is True
    assert record.capability["incoming_resource_trigger_basis"] is True
    for name in (
        "incoming_player_damage_runtime", "armor_mitigation_runtime",
        "survivability_state", "incoming_resource_trigger_basis",
    ):
        assert name not in record.unsupported_mechanics
    probe = record.provenance["incoming_damage_probe"]
    assert probe["real_armor_changes_health_damage"] is True
    assert probe["rage_basis_independent_of_real_armor"] is True
    assert probe["zero_armor"]["rage_gained"] == pytest.approx(probe["high_armor"]["rage_gained"])
    assert probe["legacy_fallback"] is False

    runtime_source = Path("src/game/runtime/simulator.py").read_text(encoding="utf-8").lower()
    assert "if class" not in runtime_source
    assert "druid" not in runtime_source
    assert "bear" not in runtime_source
    assert "Generic incoming damage + mitigation" in DECISIONS_HTML
    assert "function genericIncomingDamageSummary(r)" in DECISIONS_HTML
