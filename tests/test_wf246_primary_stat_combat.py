"""Source-backed primary stat -> actual damage, avoidance, health, talent checks."""
import sqlite3
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.primary_stat_conversions import (
    load_primary_stat_conversions, source_enrich_primary_stats)
from src.game.gear import apply_gear_selection
from src.game.talents import apply_talent_selection
from src.game.runtime.state import ActorState
from src.game.runtime.simulator import expected_auto_attack_swing, expected_incoming_attack


def _actor(ir):
    return ActorState.from_ir(ir.actor, ir.resources, ir.modes)


def test_sqlite_primary_source_and_provenance():
    facts = load_primary_stat_conversions('druid')
    assert len(facts) == 5  # WF309 adds sourced global Intellect -> mana aura delta
    assert all(f.source_url.startswith('https://') and f.capture_id for f in facts)
    assert {f.target_id for f in facts} == {
        'attack_power', 'melee_crit_chance', 'dodge_chance', 'health', 'mana'}
    assert next(f for f in facts if f.target_id == 'health').baseline == 'delta_only'
    assert next(f for f in facts if f.target_id == 'health').threshold == 20
    ir = build_game_ir_slice(class_key='druid', level=20)
    assert ir.actor.base_stats['attack_power'] == pytest.approx(60.)
    assert ir.actor.base_stats['melee_crit_chance'] == pytest.approx(.012)
    assert ir.actor.base_stats['dodge_chance'] == pytest.approx(.012)
    assert next(r for r in ir.resources if r.id == 'health').capacity == 500.  # proxy unchanged
    with pytest.raises(ValueError, match='twice'):
        source_enrich_primary_stats(ir)


def test_gear_stat_deltas_reach_melee_damage_incoming_and_hp_without_double_count():
    source = build_game_ir_slice(class_key='druid', level=20)
    geared, applied = apply_gear_selection(source, aggregate_stats={
        'strength': 10., 'agility': 20., 'stamina': 5.}, selected_items=())
    assert applied.unsupported_stats == {}
    assert geared.actor.base_stats['attack_power'] == pytest.approx(80.)
    assert geared.actor.base_stats['melee_crit_chance'] == pytest.approx(.022)
    assert geared.actor.base_stats['dodge_chance'] == pytest.approx(.022)
    assert next(r for r in geared.resources if r.id == 'health').capacity == pytest.approx(550.)
    old, new = _actor(source), _actor(geared)
    old.transition_mode('cat'); new.transition_mode('cat')
    # +20 AP from 10 Strength; +20 AP from 20 Agility in Cat.
    assert new.stats['attack_power'] - old.stats['attack_power'] == pytest.approx(40.)
    attack = next(a for a in source.auto_attacks if a.required_mode_id == 'cat')
    assert expected_auto_attack_swing(attack, actor=new)['expected_damage'] > (
        expected_auto_attack_swing(attack, actor=old)['expected_damage'])
    incoming = source.incoming_attacks[0]
    assert expected_incoming_attack(incoming, actor=new, mitigation_rules=source.mitigation_rules)[
        'post_mitigation_damage'] < expected_incoming_attack(
        incoming, actor=old, mitigation_rules=source.mitigation_rules)['post_mitigation_damage']
    old.transition_mode('bear'); new.transition_mode('bear')
    # +5 gear Stamina is +50 HP globally; never another +50 in Bear.
    assert new.resource_capacity['health'] - old.resource_capacity['health'] == pytest.approx(50.)
    assert new.stats['attack_power'] - old.stats['attack_power'] == pytest.approx(20.)


def test_heart_of_wild_talent_uses_total_strength_and_stamina_not_gear_twice():
    source = build_game_ir_slice(class_key='druid', level=20)
    geared, _ = apply_gear_selection(source, aggregate_stats={
        'strength': 10., 'stamina': 5.}, selected_items=())
    talented, applied = apply_talent_selection(geared, {'heart_of_the_wild': 5}, level=20)
    assert applied.applied_modifiers
    before, after = _actor(geared), _actor(talented)
    before.transition_mode('cat'); after.transition_mode('cat')
    assert after.stats['attack_power'] - before.stats['attack_power'] == pytest.approx(8.)
    before.transition_mode('bear'); after.transition_mode('bear')
    assert after.resource_capacity['health'] - before.resource_capacity['health'] == pytest.approx(86.)


def test_source_fail_closed_for_missing_stat_and_malformed_canonical_rule(tmp_path):
    source = build_game_ir_slice(class_key='druid', level=20)
    raw = replace(source, actor=replace(source.actor, metadata={
        k: v for k, v in source.actor.metadata.items() if k != 'canonical_primary_stat_conversions'},
        base_stats={'stamina': 10.}))
    with pytest.raises(ValueError, match='source absent'):
        source_enrich_primary_stats(raw)
    src_db = tmp_path / 'malformed.sqlite'
    with sqlite3.connect(src_db) as c:
        c.execute('''CREATE TABLE actor_stat_conversion_source_facts (
            class_key TEXT,source_stat TEXT,target_type TEXT,target_id TEXT,
            coefficient REAL,baseline TEXT,authority TEXT,source_url TEXT,
            source_date TEXT,evidence TEXT,capture_id TEXT,
            operation TEXT,threshold REAL,below_coefficient REAL)''')
        c.execute('INSERT INTO actor_stat_conversion_source_facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('druid','strength','stat','attack_power',-2.,'total','source','https://example.test',
             '2026-10-11','bad coefficient','test','linear',None,None))
    with pytest.raises(ValueError, match='invalid'):
        load_primary_stat_conversions('druid', db_path=src_db)


def test_piecewise_stamina_gear_conversion_respects_source_threshold():
    from src.game.data.forever.primary_stat_conversions import converted_stat_amount
    fact = next(f.as_dict() for f in load_primary_stat_conversions('druid')
                if f.target_id == 'health')
    assert converted_stat_amount(fact, 18) == pytest.approx(18.)
    assert converted_stat_amount(fact, 20) == pytest.approx(20.)
    assert converted_stat_amount(fact, 22) == pytest.approx(40.)
    assert converted_stat_amount(fact, 22) - converted_stat_amount(fact, 18) == pytest.approx(22.)
