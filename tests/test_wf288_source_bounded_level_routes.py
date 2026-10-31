"""Native scored consecutive levels, never misrepresented as product-ready route."""
from dataclasses import replace
import pytest

from src.game.level_legality import LevelState, validate_level_transition, validate_level_state
from src.v2.source_budgeted_level_route import search_source_bounded_level_route


def test_contiguous_real_druid_l2_and_legal_talent_transitions():
    result = search_source_bounded_level_route(class_key='druid', start_level=10,
        end_level=12, max_active_paths=1, max_children_per_path=2,
        max_l2_per_state=8, max_total_events=6000)
    assert result['status']=='EVALUATED_CONTIGUOUS_BOUNDED_SOURCE_SCENARIO'
    assert [r['level'] for r in result['selected_route']]==[10,11,12]
    assert all(r['scratch_verification_complete'] and r['real_l2_attempts'] >= 3
               and r['full_cycle_s_per_mob'] > 0 for r in result['selected_route'])
    assert all(r['source_legal_transition']['status']=='LEGAL_SOURCE_TRANSITION'
               for r in result['selected_route'][1:])
    assert result['compute']['l2_attempts']<=result['global_budget']['max_l2_attempts']
    assert result['compute']['event_transitions']<=result['global_budget']['max_events']
    assert result['full_route_complete'] is False
    assert result['accepted_class_level_checkpoints']==0
    assert result['named_gear_acquisition_verified'] is False
    assert result['cross_level_resource_carry_verified'] is False


def test_cross_class_real_auto_continuation_route():
    for cls in ('hunter','warrior'):
        result=search_source_bounded_level_route(class_key=cls, start_level=10,
            end_level=11, max_active_paths=1,max_children_per_path=1,
            max_l2_per_state=8, max_total_events=4000)
        assert result['status']=='EVALUATED_CONTIGUOUS_BOUNDED_SOURCE_SCENARIO'
        assert all(step['scratch_verification_complete'] for step in result['selected_route'])
        assert result['compute']['event_transitions']>0


def test_no_fake_gear_acquisition_or_illegal_level_jump():
    a=LevelState('druid',10,'tauren',{'improved_wrath':1},('wrath:5177',))
    b=LevelState('druid',11,'tauren',{'improved_wrath':2},('wrath:5177',))
    assert validate_level_transition(a,b)['route_complete'] is False
    with pytest.raises(ValueError, match='nonconsecutive'):
        validate_level_transition(a,replace(b,level=12))
    with pytest.raises(ValueError, match='gear legality'):
        validate_level_state(replace(a,gear_scenario='magic_items',selected_items=('item:1',)))
    with pytest.raises(ValueError, match='refund'):
        validate_level_transition(a,replace(b,talents={}))
    with pytest.raises(ValueError, match='unavailable'):
        validate_level_state(replace(a,action_ids=('fake_spell:999999',)))


def test_route_compute_cap_not_promoted_to_complete():
    result=search_source_bounded_level_route(class_key='druid',start_level=10,
        end_level=13,max_active_paths=1,max_children_per_path=2,
        max_l2_per_state=6,max_total_l2_attempts=6,max_total_events=800)
    assert result['status']=='PARTIAL_BOUNDED_SOURCE_SCENARIO'
    assert result['last_contiguous_level'] in (None,10)
    assert result['compute']['l2_attempts']<=6
    assert result['compute']['event_transitions']<=800
    assert result['full_route_complete'] is False
