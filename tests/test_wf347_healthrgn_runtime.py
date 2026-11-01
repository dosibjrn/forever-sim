"""WF347: sourced Forever HP5 affects real CombatRuntime and recovery clocks."""
from dataclasses import replace
from math import isclose
import json
from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p3 import checkpoint_item_l0, source_item_l0
from src.game.recovery import recover_actor_to_full
from src.game.recovery_hot import _simulate
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.gear import apply_stat_delta, executable_gear_stats
from src.rulesets.forever.items.runtime_selection import available_items
from src.rulesets.forever.items.source_numeric_extras import (
    modeled_source_numeric_extras, apply_source_numeric_extras,
)
from src.rulesets.forever.shared.recovery import food_tier, water_tier


def test_source_field_hp5_all_five_legal_items_without_per_item_executor_branches():
    rows = {i.item_id:i for i in available_items('druid',20,required_level_policy='observed')}
    expected = {14149:5,284192:4,6226:7,284668:5,6461:10}
    for iid,amount in expected.items():
        item=rows[iid]
        assert item.extra_stats['healthrgn']==amount
        assert modeled_source_numeric_extras(item)['health_regeneration_per_5s']==amount
        assert source_item_l0(item)['l2_effect_fully_supported']
    certificate=checkpoint_item_l0(class_key='druid',level=20)
    assert certificate['legal_item_count']==certificate['l0_assessed_count']==1171
    assert certificate['unknown_effect_item_count']==29
    assert all(iid in {r['item_id'] for r in certificate['source_items']} for iid in expected)


def test_source_numeric_healthrgn_changes_real_combat_actor_resource():
    ir=build_game_ir_slice(class_key='druid',level=20)
    item_ir=apply_source_numeric_extras(ir,class_key='druid',level=20,item_ids=(6461,))
    assert item_ir.actor.base_stats['health_regeneration_per_5s']==10
    assert item_ir.provenance['source_numeric_extra_effects'][0]['source_url'].endswith('item=6461')
    actor=ActorState.from_ir(item_ir.actor,item_ir.resources,item_ir.modes)
    assert actor.resource_regeneration_per_s['health']==pytest.approx(2)
    actor.deplete('health',50)
    before=actor.resource_amount('health')
    runtime=CombatRuntime(actor=actor,target=TargetState.with_health('target',500))
    runtime.advance_to(5.)
    assert actor.resource_amount('health')==pytest.approx(before+10)
    assert actor.resource_amount('health')<=actor.resource_capacity['health']


def test_hp5_adds_to_food_and_does_not_create_free_instant_recovery():
    def state(rate):
        return ActorState(id='hero',resources={'health':50.},resource_capacity={'health':100.},
                          resource_active={'health':True},resource_regeneration_per_s={'health':rate})
    regular=recover_actor_to_full(actor=state(0),level=20,actions=(),start_time_s=0)
    hp5=recover_actor_to_full(actor=state(2),level=20,actions=(),start_time_s=0)
    food=food_tier(20).rate_per_s
    assert regular.total_s==pytest.approx(50/food)
    assert hp5.total_s==pytest.approx(50/(food+2))
    assert hp5.total_s<regular.total_s
    assert hp5.resources_after['health']==100
    assert hp5.provenance['passive_health_regen_per_s']==2


def test_hp5_hot_recovery_does_not_double_count_passive_tick():
    def state(rate):
        return ActorState(id='hero',resources={'health':50.,'mana':100.},
            resource_capacity={'health':100.,'mana':100.},
            resource_active={'health':True,'mana':True},
            resource_regeneration_per_s={'health':rate,'mana':0.})
    trial, runtime, food_s, _ = _simulate(state(2),level=20,start=0.,plan=(),
        healing_power=0.,health_id='health',mana_id='mana',passive=0.)
    elapsed=trial.current_time_s
    assert elapsed==pytest.approx(50/(food_tier(20).rate_per_s+2.))
    assert trial.resource_amount('health')==pytest.approx(100.)
    assert food_s==pytest.approx(elapsed)


def test_hp5_100mob_stat_axis_is_executable_and_invalid_values_fail_closed():
    ir=build_game_ir_slice(class_key='druid',level=20)
    assert 'health_regeneration_per_5s' in executable_gear_stats(ir)
    boosted=apply_stat_delta(ir,'health_regeneration_per_5s',5.)
    assert boosted.actor.base_stats['health_regeneration_per_5s']==5.
    for invalid in (-1,float('nan'),float('inf')):
        changed=replace(ir,actor=replace(ir.actor,base_stats={**ir.actor.base_stats,
             'health_regeneration_per_5s':invalid}))
        with pytest.raises(ValueError,match='INVALID_SOURCE_HEALTH_REGEN_PER_5S'):
            ActorState.from_ir(changed.actor,changed.resources,changed.modes)


def test_recovery_deadline_is_hard_even_during_hot_candidate_enumeration():
    from time import process_time_ns,monotonic_ns
    from src.game.runtime.simulator import ComputeDeadlineExceeded
    from src.game.recovery_hot import optimize_mixed_recovery
    actor=ActorState(id='hero',resources={'health':50.,'mana':100.},
        resource_capacity={'health':100.,'mana':100.},
        resource_active={'health':True,'mana':True},
        resource_regeneration_per_s={'health':2.,'mana':0.})
    with pytest.raises(ComputeDeadlineExceeded,match='BUDGET_CPU_DEADLINE'):
        recover_actor_to_full(actor=actor,level=20,actions=(),start_time_s=0.,
            cpu_deadline_ns=process_time_ns()-1)
    with pytest.raises(ComputeDeadlineExceeded,match='BUDGET_WALL_DEADLINE'):
        optimize_mixed_recovery(actor=actor,level=20,actions=(),start_time_s=0.,
            healing_power=0.,health_resource_id='health',mana_resource_id='mana',
            passive=0.,wall_deadline_ns=monotonic_ns()-1)


def test_independent_wf347_p4_p5_have_same_source_and_100mob_saturation():
    root=Path(__file__).resolve().parents[1]
    a=json.loads((root/'evidence/wf347/WF347_P4_STRICT.json').read_text())
    b=json.loads((root/'evidence/wf347/WF347_P5_STRICT.json').read_text())
    assert a['source_context_sha256']==b['source_context_sha256']
    assert a['staged_source_sha256']==b['staged_source_sha256']
    assert a['item_catalogue_sha256']==b['item_catalogue_sha256']
    assert a['equipment_semantics_sha256']==b['equipment_semantics_sha256']
    assert a['oracle_seeded'] is b['oracle_seeded'] is False
    assert a['end_to_end_wall_s']<=30 and b['end_to_end_wall_s']<=300
    assert b['distinct_paid_complete_stages_lower_bound']>=1.3*a['distinct_paid_complete_stages_lower_bound']
    assert a['winner']['actual_100mob_s_per_mob']<=1.01*b['winner']['actual_100mob_s_per_mob']
    assert a['winner']['gear']==b['winner']['gear']
    assert a['winner']['gear']['shoulder']==6461
    assert a['winner']['actual_100mob_events']==b['winner']['actual_100mob_events']
    for run in (a,b):
        assert run['total_events']==run['joint_events']+run['persistent_events']+run['slot_events']
        assert run['slot_screen_completed']>0 and run['slot_100mob_evaluations']>=2
        assert run['winner']['predicted_100mob_s_per_mob_from_3mob_screen']>0
        assert run['winner']['actual_100mob_s_per_mob']>0
