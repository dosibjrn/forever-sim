"""Regression for the production source-authorized '*' equipped-weapon mode.

The source fact below is a *test fixture*, never a claim of real Rogue
acquisition or P3 acceptance. The action, damage and combat runtime are real.
"""
from dataclasses import replace
from types import SimpleNamespace

import src.game.gear as gear
from src.game.checkpoint_p3_smoke import policy_uses_equipped_weapon_damage
from src.game.data.forever.registry import build_game_ir_slice
from src.game.model.ir import WeaponDamageEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState


def _rogue_builder():
    ir = build_game_ir_slice(class_key="rogue", level=20)
    assert ir is not None
    action = next(a for a in ir.actions if a.family_key == "sinister_strike")
    effect = next(e for e in action.effects if isinstance(e, WeaponDamageEffect))
    assert not any(r.get("kind") == "mode_is" for r in action.requirements)
    return ir, action, effect


def _damage(ir, action):
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    target = TargetState.with_health("source_weapon_target", 100000., armor=0.)
    runtime = CombatRuntime(actor=actor, target=target, auto_attacks=())
    runtime.schedule_action(action)
    runtime.advance_to(max(0.1, actor.current_time_s + 0.01))
    return 100000. - target.health


def test_wildcard_weapon_fact_updates_real_direct_weapon_action_and_damage(monkeypatch):
    ir, action, effect = _rogue_builder()
    # A canonical mode fact with '*' means all matching weapon-source actions,
    # not the impossible requirement mode_is(None). Keep the source kind taken
    # from the actual GameIR, never a class-specific action-name dispatch.
    source_fact = SimpleNamespace(
        source_stat="weapon_dps", damage_source_kind=effect.damage_source.kind,
        mode_label="*", source_url="https://www.wowhead.com/",
        authority="test_fixture_not_acceptance", source_date="2026-11-02",
        capture_id="test_wildcard", source_item_slot="weapon",
        weapon_speed_semantics="form_fixed",
    )
    monkeypatch.setattr(gear, "_weapon_facts_for_ir",
                        lambda ir_slice, db_path=None: ((source_fact, None),))

    # The same production executor must observe the equipped weapon's DPS.
    original_damage = _damage(ir, action)
    original_dps = float(ir.actor.base_stats["weapon_dps"])
    equipped_dps = original_dps + 15.0
    assert "weapon_dps" in gear.executable_gear_stats(ir)
    selected, receipt = gear.apply_gear_selection(
        ir, aggregate_stats={"weapon_dps": equipped_dps},
        source="generic_stat_sensitivity_probe")
    selected_action = next(a for a in selected.actions if a.id == action.id)
    selected_effect = next(e for e in selected_action.effects
                           if isinstance(e, WeaponDamageEffect))
    assert receipt.applied_stats["weapon_dps"] == equipped_dps
    assert selected_effect.damage_source.dps_stat_id is None
    assert selected_effect.damage_source.flat_dps == equipped_dps
    assert _damage(selected, selected_action) > original_damage

    # The P3 policy predicate must see the same sourced wildcard dependence
    # even after gear application removes the actor's dps_stat_id reference.
    assert policy_uses_equipped_weapon_damage(selected, ir.policies[0])


def test_weapon_action_without_auto_attacks_remains_an_executable_gear_axis(monkeypatch):
    ir, action, effect = _rogue_builder()
    fact = SimpleNamespace(source_stat="weapon_dps",
        damage_source_kind=effect.damage_source.kind, mode_label="*")
    monkeypatch.setattr(gear, "_weapon_facts_for_ir",
                        lambda ir_slice, db_path=None: ((fact, None),))
    no_auto = replace(ir, auto_attacks=())
    assert "weapon_dps" in gear.executable_gear_stats(no_auto)


def test_real_druid_source_weapon_dps_probe_changes_bear_combat_damage():
    """No injected facts: the pinned Forever SQLite authorizes Bear/Cat DPS."""
    ir = build_game_ir_slice(class_key="druid", level=60)
    assert ir is not None
    facts = gear._weapon_facts_for_ir(ir)
    assert any(f.source_stat == "weapon_dps" and mode == "bear"
               for f, mode in facts)
    before = next(a for a in ir.auto_attacks if a.required_mode_id == "bear")
    assert before.damage_source.flat_dps > 0
    after_ir = gear.apply_stat_delta(ir, "weapon_dps", 5.0)
    after = next(a for a in after_ir.auto_attacks if a.id == before.id)
    assert after.damage_source.flat_dps == before.damage_source.flat_dps + 5.0
    assert after.damage_source.dps_stat_id is None
    # This is the SAME genuine CombatRuntime used for source gear scoring.
    def swing_damage(source_ir, attack):
        actor = ActorState.from_ir(source_ir.actor, source_ir.resources,
                                   source_ir.modes)
        actor.transition_mode("bear")
        target = TargetState.with_health("real_source_bear_target", 100000.,
                                        armor=0.)
        runtime = CombatRuntime(actor=actor, target=target,
                                auto_attacks=(attack,))
        runtime.advance_to(float(attack.swing_time_s) + 0.01)
        return 100000. - target.health

    old_damage = swing_damage(ir, before)
    new_damage = swing_damage(after_ir, after)
    assert old_damage > 0
    assert new_damage > old_damage
