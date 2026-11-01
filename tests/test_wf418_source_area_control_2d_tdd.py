"""WF418 RED: source-verified actor-centered AoE damage/control on one 2D runtime."""
from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.model import (ActorDefinition, ResourceDefinition, ActionDefinition,
                            DamageEffect, ControlEffect, ResourceCost)
from src.game.runtime import ActorState, CombatRuntime, TargetState


def _pack(action):
    actor = ActorState.from_ir(ActorDefinition('player', 'player', base_stats={}, metadata={'level':30}), (
        ResourceDefinition('health', 'Health', 'player', initial_amount=600, capacity=600),
        ResourceDefinition('mana', 'Mana', 'player', initial_amount=300, capacity=300)), ())
    targets = [TargetState.with_health(f'm{i}', 200) for i in range(3)]
    rt = CombatRuntime(actor=actor, target=targets[0], other_targets=targets[1:],
                       spatial_positions_yards={'m0': (2, 0), 'm1': (8, 0), 'm2': (20, 0)},
                       enemy_move_speed_yards_s=5)
    return rt, targets


def _source_nova(level=30):
    ir = build_game_ir_slice(class_key='mage', level=level)
    return next(a for a in ir.actions if a.family_key == 'frost_nova')


def test_real_forever_frost_nova_aoe_fact_from_canonical_sqlite():
    with sqlite3.connect(DEFAULT_DB) as db:
        rows = db.execute('SELECT spell_id,radius_yards,center,source_url,source_build '
                          'FROM verified_spell_area_facts WHERE spell_id IN (122,865) '
                          'ORDER BY spell_id').fetchall()
    assert len(rows) == 2
    assert all(r[1] == 10 and r[2] == 'actor' and 'forever' in r[3]
               and r[4] for r in rows)
    for level, sid in ((20, 122), (30, 865)):
        nova = _source_nova(level)
        assert nova.id.endswith(':' + str(sid))
        assert nova.metadata['aoe_radius_yards'] == pytest.approx(10.)
        assert nova.metadata['aoe_center'] == 'actor'
        assert nova.metadata['aoe_source']['spell_id'] == sid
        assert all(effect.target == 'enemies' for effect in nova.effects
                   if isinstance(effect, (DamageEffect, ControlEffect)))


def test_real_source_nova_hits_and_roots_all_nearby_but_not_distant_targets():
    nova = _source_nova()
    rt, targets = _pack(nova)
    before = rt.actor.resource_amount('mana')
    rt.schedule_action(nova)
    assert rt.actor.resource_amount('mana') == pytest.approx(before - nova.costs[0].amount)
    assert [t.health for t in targets] == pytest.approx([200-36.5, 200-36.5, 200])
    assert set(e.target_id for e in rt.result().events if e.kind == 'Damage'
               and e.action_id == nova.id and e.payload.get('applied')) == {'m0', 'm1'}
    for t in targets[:2]:
        assert t.active_controls.get('root', 0) >= 8.
        assert t.active_controls.get('frozen', 0) >= 8.
    assert not targets[2].active_controls
    assert len([e for e in rt.result().events if e.kind == 'ActionStarted'
                and e.action_id == nova.id]) == 1
    rt.engage_target('m1'); rt.engage_target('m2')
    rt.advance_to(2.)
    assert rt._enemy_distance('m1') == pytest.approx(8.)
    assert rt._enemy_distance('m2') == pytest.approx(10.)
    assert 'm1' not in rt._melee_targets
    assert 'm2' not in rt._melee_targets


def test_actor_centered_area_is_not_tied_to_selected_distant_target():
    nova = _source_nova()
    rt, targets = _pack(nova)
    rt.select_target('m2')
    rt.schedule_action(nova)
    assert targets[0].health < 200 and targets[1].health < 200
    assert targets[2].health == pytest.approx(200)
    assert 'root' not in targets[2].active_controls


def test_area_control_requires_positive_sourced_radius_before_spending_mana():
    action = ActionDefinition(id='area:fixture', family_key='area', name='Area fixture',
        owner_actor_id='player', requirements=(), costs=(ResourceCost('mana', 10),),
        cast_time_s=0, gcd_s=1.5, cooldown_s=10,
        effects=(ControlEffect('control', 'root', 'enemies', 8),),
        provenance=({'fixture': 'generic_area'},), metadata={'aoe_center': 'actor'})
    rt, targets = _pack(action)
    with pytest.raises(ValueError, match='AOE_SOURCE_RADIUS_UNAVAILABLE'):
        rt.schedule_action(action)
    assert rt.actor.resource_amount('mana') == pytest.approx(300.)
    assert not any(t.active_controls for t in targets)


def test_area_control_and_damage_use_one_victim_set_and_one_paid_action():
    action = ActionDefinition(id='area:fixture', family_key='area', name='Area fixture',
        owner_actor_id='player', requirements=(), costs=(ResourceCost('mana', 10),),
        cast_time_s=0, gcd_s=1.5, cooldown_s=10,
        effects=(DamageEffect('damage', 'frost', 'enemies', 10, 10),
                 ControlEffect('control', 'root', 'enemies', 8)),
        provenance=({'fixture': 'generic_area'},),
        metadata={'aoe_center': 'actor', 'aoe_radius_yards': 10.,
                  'aoe_source': {'spell_id': 1, 'source_url': 'fixture:source'}})
    rt, targets = _pack(action)
    rt.schedule_action(action)
    assert [t.health for t in targets] == pytest.approx([190, 190, 200])
    assert set(e.target_id for e in rt.result().events if e.kind == 'ControlApplied') == {'m0','m1'}
    assert rt.actor.resource_amount('mana') == pytest.approx(290.)


def test_source_aoe_control_keeps_contextual_guard_and_paid_policy_frontier():
    from src.v2.source_bounded_joint_frontier import source_cold_start_stage, source_joint_policy_frontier
    from src.game.policy_evolution import _semantic_guards
    ir = build_game_ir_slice(class_key='mage', level=20)
    nova = next(a for a in ir.actions if a.family_key == 'frost_nova')
    assert any(e.target == 'enemies' for e in nova.effects if isinstance(e, ControlEffect))
    assert any(c.kind == 'target_control_missing' and c.value == 'root'
               for c in _semantic_guards(nova))
    stage = source_cold_start_stage(class_key='mage', level=20, source_ir=ir,
                                    gear_role='mage_frost')
    frontier = source_joint_policy_frontier(ir, stage, max_policies=5)
    assert any(origin == 'control_opening' and p.rules[0].action_id == nova.id
               for origin, p in frontier)


def test_source_nova_survives_paid_100_mob_2d_chain_and_is_not_assumed_optimal():
    """A 20-yd pack uses the real GameIR->APL->CombatRuntime->recovery path."""
    from src.game.policy_evolution import from_source_rules, _semantic_guards
    from src.game.multi_pull import evaluate_repeated_pulls
    ir = build_game_ir_slice(class_key='mage', level=30)
    nova = next(a for a in ir.actions if a.family_key == 'frost_nova')
    filler = next(a for a in ir.actions if a.family_key == 'frostbolt')
    policies = (
        from_source_rules(ir, ((filler.id, _semantic_guards(filler)),),
                          provenance='wf418_no_control'),
        from_source_rules(ir, ((nova.id, _semantic_guards(nova)),
                               (filler.id, _semantic_guards(filler))),
                          provenance='wf418_area_control'),
    )
    results = [evaluate_repeated_pulls(ir_slice=ir, policy=p, level=30,
        target_health=200, count=100, pack_size=2,
        schedule_incoming_attacks=True) for p in policies]
    for result in results:
        assert len(result.pulls) == 50
        assert sum(p['mob_count'] for p in result.pulls) == 100
        assert all(p['pack_all_defeated'] for p in result.pulls)
        assert sum(p['event_transitions'] for p in result.pulls) > 1000
        assert sum(p['recovery_s'] for p in result.pulls) > 0
    casts = [a['action_id'] for pack in results[1].pulls
             for a in pack['selected_actions']]
    assert casts.count(nova.id) > 0
    assert results[0].seconds_per_mob < results[1].seconds_per_mob


def test_area_radius_comes_from_selected_sqlite_snapshot_not_spell_name(tmp_path):
    from shutil import copyfile
    stage = tmp_path / 'staged_area.sqlite'
    copyfile(DEFAULT_DB, stage)
    with sqlite3.connect(stage) as db:
        db.execute('UPDATE verified_spell_area_facts SET radius_yards=6 '
                   'WHERE spell_id=865')
    staged_ir = build_game_ir_slice(class_key='mage', level=30,
                                    ability_db_path=stage)
    staged = next(a for a in staged_ir.actions if a.family_key == 'frost_nova')
    assert staged.metadata['aoe_radius_yards'] == pytest.approx(6.)
    assert _source_nova().metadata['aoe_radius_yards'] == pytest.approx(10.)
    rt, targets = _pack(staged)
    rt.schedule_action(staged)
    assert [t.health for t in targets] == pytest.approx([163.5, 200., 200.])
