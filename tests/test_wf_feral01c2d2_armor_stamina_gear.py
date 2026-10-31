"""WF-FERAL01c2d2: named item armor and sourced mode-limited Stamina.

This is a real generic runtime execution proof, NOT an ordinary-policy incoming
hit integration or full weapon-DPS fidelity proof.
"""
from __future__ import annotations

from dataclasses import replace
import shutil
import sqlite3

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.gear import select_named_gear
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.gear import apply_gear_selection, apply_stat_delta, executable_gear_stats
from src.game.model import ActorDefinition, GameIRSlice, ModeDefinition, ResourceDefinition
from src.game.runtime import ActorState, CombatRuntime, TargetState


def _actor(ir):
    return ActorState.from_ir(ir.actor, ir.resources, ir.modes)


def test_real_named_gear_armor_reduces_incoming_damage_and_stamina_adds_bear_health():
    source = build_source_slice(20)
    gear = select_named_gear(class_key='druid', level=20, role='druid_bear',
                             stat_weights={'armor': 1, 'stamina': 1})
    assert gear.aggregate_stats['armor'] > 0 and gear.aggregate_stats['stamina'] > 0
    equipped, application = apply_gear_selection(source, aggregate_stats=gear.aggregate_stats,
                                                  selected_items=tuple(gear.slots.values()))
    assert application.applied_stats['armor'] == gear.aggregate_stats['armor']
    assert application.applied_stats['stamina'] == gear.aggregate_stats['stamina']
    assert application.partial_stats['stamina']['modes'] == ['bear_form']
    assert application.applied_stats['weapon_dps'] > 0  # now sourced and executed
    naked = _actor(source)
    geared = _actor(equipped)
    assert geared.stats['armor'] - naked.stats['armor'] == pytest.approx(
        gear.aggregate_stats['armor'] + 2 * gear.aggregate_stats.get('agility', 0))
    assert geared.resource_capacity['health'] == naked.resource_capacity['health']  # mode-limited
    naked.transition_mode('bear')
    geared.transition_mode('bear')
    assert geared.resource_capacity['health'] - naked.resource_capacity['health'] == pytest.approx(
        gear.aggregate_stats['stamina'] * 10)
    n = CombatRuntime(actor=naked, target=TargetState.with_health('n', 1000))
    g = CombatRuntime(actor=geared, target=TargetState.with_health('g', 1000))
    n_hit = n.resolve_incoming_attack(source.incoming_attacks[0], mitigation_rules=source.mitigation_rules)
    g_hit = g.resolve_incoming_attack(equipped.incoming_attacks[0], mitigation_rules=equipped.mitigation_rules)
    assert g_hit['health_damage_applied'] < n_hit['health_damage_applied']
    assert g_hit['armor'] > n_hit['armor']
    ratio = geared.resource_amount('health') / geared.resource_capacity['health']
    for _ in range(3):
        geared.transition_mode('caster')
        assert geared.resource_capacity['health'] == pytest.approx(500)
        assert geared.resource_amount('health') / 500 == pytest.approx(ratio)
        geared.transition_mode('bear')
        assert geared.resource_capacity['health'] == pytest.approx(500 + 10 * gear.aggregate_stats['stamina'])
        assert geared.resource_amount('health') / geared.resource_capacity['health'] == pytest.approx(ratio)


def test_stamina_conversion_mutation_and_removal_are_source_authoritative(tmp_path):
    clone = tmp_path / 'copy.sqlite'
    shutil.copyfile(DEFAULT_DB, clone)
    source = build_source_slice(20)
    with sqlite3.connect(clone) as db:
        db.execute("UPDATE stat_conversion_source_facts SET coefficient=12 WHERE class_key='druid' AND source_stat='stamina'")
    changed, report = apply_gear_selection(source, aggregate_stats={'stamina': 5}, db_path=clone)
    actor = _actor(changed)
    actor.transition_mode('bear')
    assert actor.resource_capacity['health'] == pytest.approx(560)
    assert report.applied_stats['stamina'] == 5
    with sqlite3.connect(clone) as db:
        db.execute("DELETE FROM stat_conversion_source_facts WHERE class_key='druid' AND source_stat='stamina'")
    assert 'stamina' not in executable_gear_stats(source, db_path=clone)
    _, unsupported = apply_gear_selection(source, aggregate_stats={'stamina': 5}, db_path=clone)
    assert unsupported.unsupported_stats['stamina'] == 5
    with pytest.raises(ValueError, match='no executable generic gear semantic'):
        apply_stat_delta(source, 'stamina', 5, db_path=clone)


def test_synthetic_non_druid_resource_and_mode_from_sqlite(tmp_path):
    clone = tmp_path / 'synthetic.sqlite'
    shutil.copyfile(DEFAULT_DB, clone)
    with sqlite3.connect(clone) as db:
        db.execute('''INSERT INTO stat_conversion_source_facts
            (class_key,source_stat,target_type,target_id,mode_label,coefficient,authority,source_url,capture_id)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            ('synthetic','resolve','resource_capacity','barrier','wolf_form',3,
             'synthetic_test_fact','https://example.org/test','synthetic-test'))
    source = build_source_slice(20)
    ir = replace(source,
        actor=ActorDefinition(id='player', actor_type='player',
            base_stats={'resolve': 8}, metadata={'class_key': 'synthetic', 'level': 20}),
        resources=(ResourceDefinition(id='barrier', name='Barrier', owner_actor_id='player',
                                      initial_amount=100, capacity=100),),
        modes=(ModeDefinition(id='normal', label='Normal', initial=True),
               ModeDefinition(id='wolf', label='Wolf Form')))
    geared, report = apply_gear_selection(ir, aggregate_stats={'resolve': 7}, db_path=clone)
    assert report.partial_stats['resolve']['modes'] == ['wolf_form']
    actor = _actor(geared)
    assert actor.resource_capacity['barrier'] == 100
    actor.transition_mode('wolf')
    assert actor.resource_capacity['barrier'] == 121
    actor.transition_mode('normal')
    assert actor.resource_capacity['barrier'] == 100
    with sqlite3.connect(clone) as db:
        db.execute("UPDATE stat_conversion_source_facts SET target_id='missing' WHERE class_key='synthetic'")
    assert 'resolve' not in executable_gear_stats(ir, db_path=clone)
    _, unsupported = apply_gear_selection(ir, aggregate_stats={'resolve': 7}, db_path=clone)
    assert unsupported.unsupported_stats['resolve'] == 7


def test_armor_is_source_driven_and_bear_multiplier_applies_to_items_only():
    source = build_source_slice(20)
    ir, application = apply_gear_selection(source, aggregate_stats={'armor': 130})
    assert application.applied_stats['armor'] == 130
    assert not application.partial_stats
    actor = _actor(ir)
    assert actor.stats['armor'] == 178
    actor.transition_mode('cat')
    assert actor.stats['armor'] == pytest.approx(178)
    actor.transition_mode('bear')
    assert actor.stats['armor'] == pytest.approx(48 + 2.8*130)
    actor.transition_mode('caster')
    assert actor.stats['armor'] == pytest.approx(178)
    assert next(m for m in source.modes if m.id == 'bear').metadata['item_armor_multiplier'] == 2.8


def test_repeated_stamina_gear_and_sensitivity_do_not_double_apply_capacity():
    source = build_source_slice(20)
    first, _ = apply_gear_selection(source, aggregate_stats={'stamina': 4})
    second = apply_stat_delta(first, 'stamina', 3)
    bear = _actor(second)
    bear.transition_mode('bear')
    assert bear.resource_capacity['health'] == pytest.approx(570)
    assert len(next(m for m in second.modes if m.id == 'bear').resource_capacity_modifiers) == 1
    assert second.actor.base_stats['stamina'] == pytest.approx(source.actor.base_stats['stamina'] + 7)


def test_geared_stamina_stacks_with_source_heart_without_double_counting():
    from src.game.talents import apply_talent_selection
    source = build_source_slice(20)
    geared, _ = apply_gear_selection(source, aggregate_stats={'stamina': 10})
    talented, _ = apply_talent_selection(geared, {'heart_of_the_wild': 3}, level=20)
    actor = _actor(talented)
    actor.transition_mode('bear')
    # Base health proxy 500, item +100, Heart rank 3 +12% of total
    # (base 38 + equipped 10) Stamina converted with sourced 10 HP/stat.
    assert actor.resource_capacity['health'] == pytest.approx(500 + 100 + 48 * .12 * 10)
    actor.transition_mode('caster')
    assert actor.resource_capacity['health'] == pytest.approx(500)
