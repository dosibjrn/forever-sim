"""WF368: source gear is paid by the existing CombatRuntime, not a role proxy."""
from __future__ import annotations
import hashlib,os
from pathlib import Path
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.gear import available_gear_roles,select_named_gear
from src.game.gear import apply_gear_selection
from src.game.data.forever.source_checkpoint_p3_ratings import apply_source_equipped_item_stats
from src.rulesets.forever.items.runtime_selection import (
    _source_class_profile,clear_runtime_item_cache,gear_overrides,available_items)
from src.rulesets.forever.items.source_equipment_semantics import apply_equipped_source_effects
from src.rulesets.forever.items.source_numeric_extras import apply_source_numeric_extras
from src.v2.source_persistent_joint_finalists import PreparedCandidate,evaluate_persistent_candidate
from tools.wf368_warrior_l30_gear_runtime_bridge import stage

ROOT=Path(__file__).resolve().parents[1]
ABILITY=ROOT/'data/forever/staged_warrior_l30_gear_runtime_wf368.sqlite'
ITEMS=ROOT/'data/forever/staged_warrior_l30_gear_provisional_wf365.sqlite'

@pytest.fixture(autouse=True)
def _catalogue(monkeypatch):
    monkeypatch.setenv('FOREVER_ITEM_CATALOGUE',str(ITEMS))
    clear_runtime_item_cache()
    yield
    clear_runtime_item_cache()


def _arms():
    ir=build_game_ir_slice(class_key='warrior',level=30,ability_db_path=ABILITY)
    weights=_source_class_profile('warrior')['gear_selection_roles']['warrior_arms']['proxy_weights']
    gear=select_named_gear(class_key='warrior',level=30,role='warrior_arms',stat_weights=weights,
        required_level_policy='observed',exclude_unknown_item_effects=True)
    equipped,report=apply_gear_selection(ir,aggregate_stats=gear.aggregate_stats,
        selected_items=tuple(gear.slots.values()),db_path=ABILITY)
    ids=[int(x['item_id']) for x in gear.slots.values()]
    equipped=apply_source_equipped_item_stats(equipped,class_key='warrior',level=30,item_ids=ids)
    equipped=apply_equipped_source_effects(equipped,class_key='warrior',level=30,item_ids=ids)
    equipped=apply_source_numeric_extras(equipped,class_key='warrior',level=30,item_ids=ids)
    return ir,gear,equipped,report


def test_source_roles_and_staged_sqlite_integrity(tmp_path):
    assert set(available_gear_roles('warrior'))=={
        'warrior_arms','warrior_fury','warrior_protection','warrior_unrestricted'}
    before=hashlib.sha256((ROOT/'data/forever/catalogue/forever_abilities.sqlite').read_bytes()).hexdigest()
    result=stage(destination=tmp_path/'warrior_source.sqlite')
    assert result['conversion_rows']==4 and result['weapon_rows']==1
    assert result['integrity']=='ok' and result['membership_proven'] is False
    after=hashlib.sha256((ROOT/'data/forever/catalogue/forever_abilities.sqlite').read_bytes()).hexdigest()
    assert before==after


def test_named_warrior_gear_primary_stats_and_no_weapon_double_count():
    naked,gear,equipped,report=_arms()
    assert len(gear.slots)==17
    assert not report.unsupported_stats
    assert equipped.actor.base_stats['attack_power']==pytest.approx(
        naked.actor.base_stats['attack_power']+gear.aggregate_stats['attack_power']+
        2*gear.aggregate_stats['strength'])
    assert equipped.resources[0].capacity==pytest.approx(
        naked.resources[0].capacity+10*gear.aggregate_stats['stamina'])
    assert equipped.actor.base_stats['melee_crit_chance']==pytest.approx(
        gear.aggregate_stats['agility']*.01/10.4)
    assert equipped.actor.base_stats['armor']==pytest.approx(
        gear.aggregate_stats['armor']+2*gear.aggregate_stats['agility'])
    source=equipped.auto_attacks[0].damage_source
    assert source.dps_stat_id is None  # absolute replacement, not proxy + item DPS
    assert source.flat_dps==pytest.approx(gear.slots['weapon']['weapon_dps'])
    assert equipped.auto_attacks[0].swing_time_s==pytest.approx(gear.slots['weapon']['weapon_speed'])


def test_full_100_mob_warrior_arms_with_periodic_rage_and_food_recovery():
    _,gear,ir,_=_arms()
    result=evaluate_persistent_candidate(PreparedCandidate(ir,ir.policies[0],(),{},{}),
        level=30,mobs=100,max_wall_s=8,max_cpu_s=8,max_total_events=300000)
    assert result['status']=='COMPLETE'
    assert result['count']==100 and result['continuous_actor_state'] is True
    assert result['events']>1000 and result['recovery_s']>0
    assert result['mean_s_per_mob']>0


def test_unverified_warrior_item_denominator_still_fail_closed():
    from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0
    inventory=checkpoint_item_l0(class_key='warrior',level=30)
    assert inventory['source_membership_verified'] is False
    assert inventory['p3_pass'] is False
    assert inventory['legal_item_count']==inventory['l0_assessed_count']==2951
