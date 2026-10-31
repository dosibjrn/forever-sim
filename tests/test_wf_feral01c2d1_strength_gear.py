"""WF-FERAL01c2d1: real SQLite-sourced Strength -> Cat AP gear execution."""
from __future__ import annotations

from dataclasses import replace
import shutil
import sqlite3

import pytest

from src.game.data.forever.druid import build_source_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.gear import apply_gear_selection, apply_stat_delta, executable_gear_stats
from src.game.model import ActorDefinition, GameIRSlice, ModeDefinition
from src.game.runtime import ActorState, expected_auto_attack_swing
from src.game.talents import apply_talent_selection
from src.v2.source_joint_discovery import _gear_envelope
from src.v2.source_mode_search import evaluate_discovered_mode_search


def _cat(ir):
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.transition_mode('cat')
    return actor


def test_strength_gear_changes_real_cat_attack_power_and_swing():
    source = build_source_slice(20)
    geared, report = apply_gear_selection(source, aggregate_stats={'strength': 60})
    assert report.applied_stats['strength'] == 60
    assert not report.unsupported_stats
    assert geared.actor.base_stats['strength'] == source.actor.base_stats['strength'] + 60
    assert _cat(geared).stats['attack_power'] == pytest.approx(_cat(source).stats['attack_power'] + 120)
    attack = next(a for a in source.auto_attacks if a.required_mode_id == 'cat')
    assert expected_auto_attack_swing(attack, actor=_cat(geared))['expected_damage'] > expected_auto_attack_swing(attack, actor=_cat(source))['expected_damage']
    before = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=source, max_policies_per_path=24)
    after = evaluate_discovered_mode_search(class_key='druid', level=20, ir_slice=geared, max_policies_per_path=24)
    assert after['winner']['seconds_per_mob'] < before['winner']['seconds_per_mob']


def test_heart_scales_geared_strength_without_duplicate_base_conversion():
    source = build_source_slice(20)
    geared, _ = apply_gear_selection(source, aggregate_stats={'strength': 20})
    talented, _ = apply_talent_selection(geared, {'heart_of_the_wild': 3}, level=20)
    assert _cat(talented).stats['attack_power'] == pytest.approx(36 + 20 * 2 + (30 + 20) * .06 * 2)
    # Leaving/re-entering must not compound gear or talent AP.
    actor = _cat(talented)
    for _ in range(3):
        actor.transition_mode('caster')
        actor.transition_mode('cat')
    assert actor.stats['attack_power'] == pytest.approx(_cat(talented).stats['attack_power'])


def test_sqlite_coefficient_mutation_changes_gear_execution(tmp_path):
    clone = tmp_path / 'converted.sqlite'
    shutil.copyfile(DEFAULT_DB, clone)
    with sqlite3.connect(clone) as conn:
        conn.execute("UPDATE stat_conversion_source_facts SET coefficient=3 WHERE class_key='druid' AND source_stat='strength'")
    source = build_source_slice(20)
    changed, _ = apply_gear_selection(source, aggregate_stats={'strength': 10}, db_path=clone)
    assert _cat(changed).stats['attack_power'] == pytest.approx(36 + 30)
    with sqlite3.connect(clone) as conn:
        conn.execute("DELETE FROM stat_conversion_source_facts WHERE class_key='druid' AND source_stat='strength'")
    assert 'strength' not in executable_gear_stats(source, db_path=clone)
    _, application = apply_gear_selection(source, aggregate_stats={'strength': 10}, db_path=clone)
    assert application.unsupported_stats['strength'] == 10
    with pytest.raises(ValueError, match='no executable generic gear semantic'):
        apply_stat_delta(source, 'strength', 10, db_path=clone)


def test_generic_mode_stat_conversion_for_synthetic_class(tmp_path):
    clone = tmp_path / 'synthetic.sqlite'
    shutil.copyfile(DEFAULT_DB, clone)
    with sqlite3.connect(clone) as conn:
        conn.execute('''INSERT INTO stat_conversion_source_facts
            (class_key,source_stat,target_type,target_id,mode_label,coefficient,authority,source_url,capture_id)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            ('synthetic','resolve','stat','power','wolf_form',4.0,'synthetic_test_fact',
             'https://example.org/test','test'))
    source = build_source_slice(20)
    ir = replace(source, actor=ActorDefinition(id='player', actor_type='player',
        base_stats={'resolve': 8}, metadata={'class_key':'synthetic','level':20}),
        modes=(ModeDefinition(id='normal',label='Normal',initial=True),
               ModeDefinition(id='wolf',label='Wolf Form')))
    changed, evidence = apply_gear_selection(ir, aggregate_stats={'resolve': 7}, db_path=clone)
    actor = ActorState.from_ir(changed.actor, (), changed.modes)
    actor.transition_mode('wolf')
    assert evidence.applied_stats['resolve'] == 7
    assert actor.stats['power'] == pytest.approx(28)


def test_strength_weighted_real_named_gear_is_discovered_without_legacy_seed():
    source = build_source_slice(20)
    rows = _gear_envelope('druid',20,max_gear_candidates=128,
                          include_melee_gear=True, ir_slice=source)
    strength = [r for r in rows if r['weight_vector'] == {'strength': 1.0}]
    assert strength and any(r['selection'].aggregate_stats.get('strength',0) > 0 for r in strength)
    assert any(r['gear_role']=='druid_feral' for r in rows)
    assert all(r['selection'].slots for r in rows)
    # Armor is now executable and Stamina is sourced only in Bear form.
    # Weapon DPS now executes via sourced mode-local replacement; Bear armor multiplier remains a blocker.
    ir, evidence = apply_gear_selection(source, aggregate_stats=strength[0]['selection'].aggregate_stats)
    assert evidence.applied_stats['strength'] > 0
    assert evidence.applied_stats.get('armor', 0) > 0
    assert evidence.partial_stats['stamina']['modes'] == ['bear_form']
    assert evidence.applied_stats['weapon_dps'] > 0
    assert 'weapon_dps' not in evidence.unsupported_stats


def test_held_out_feral_and_wrath_both_replayed_on_source_melee_gear():
    from tools.wf_feral01c2d1_replay import run
    result = run()
    assert result['gear_candidates'] >= 10
    assert sum(result['pairwise_wins'].values()) + result['pairwise_ties'] == result['gear_candidates']
    assert result['pairwise_wins']['old_feral_11_points'] > 0
    assert result['pairwise_wins']['improved_wrath_5'] > 0
    assert any(row['weight_vector'] == {'strength':1.0} for row in result['results'])
    assert any(row['weight_vector'] == {'agility':1.0} for row in result['results'])
    assert any(row['weight_vector'] == {'attack_power':1.0} for row in result['results'])
    assert any(row['builds']['old_feral_11_points']['best_branch'] == 'mode'
               for row in result['results'])
    assert result['source_coverage_complete'] is False
    assert any('not an unrestricted' in gap for gap in result['blocking_gaps'])
