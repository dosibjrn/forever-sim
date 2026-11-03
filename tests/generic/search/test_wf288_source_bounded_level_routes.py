"""Native scored consecutive levels, never misrepresented as product-ready route."""
from dataclasses import replace
import inspect
import pytest

from src.game.level_legality import LevelState, validate_level_transition, validate_level_state
from src.v2.source_budgeted_level_route import search_source_bounded_level_route


def test_route_api_does_not_expose_spell_acquisition_proof_inputs():
    forbidden = {
        'initial_acquisition_state', 'acquisition_events_by_level',
        'world_origin_id', 'world_events', 'world_db_path',
    }
    assert not forbidden.intersection(inspect.signature(search_source_bounded_level_route).parameters)


def test_contiguous_real_druid_l2_and_legal_talent_transitions():
    result = search_source_bounded_level_route(class_key='druid', start_level=10,
        end_level=12, max_active_paths=1, max_children_per_path=2,
        max_l2_per_state=8, max_total_events=6000)
    assert result['status']=='EVALUATED_CONTIGUOUS_BOUNDED_SOURCE_SCENARIO'
    assert not {
        'source_player_action_filter_applied',
        'source_consistent_local_acquisition_events',
        'initial_learned_spells_are_assumed_not_verified',
        'initial_acquisition_state_world_proven',
        'ability_trainer_quest_rune_acquisition_verified',
        'world_acquisition_verified',
    }.intersection(result)
    assert 'acquisition_event_attempts' not in result['compute']
    assert all(not {
        'source_consistent_acquisition', 'source_acquisition_events',
        'world_acquisition_verified',
    }.intersection(step) for step in result['selected_route'])
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


def test_route_does_not_repeat_gameir_legality_checks_after_source_frontier_and_l2(monkeypatch):
    from src.v2 import source_budgeted_level_route as route
    from src.game.data.forever.registry import build_game_ir_slice

    ir = build_game_ir_slice(class_key='druid', level=10)
    assert ir is not None

    def redundant_validation(*_args, **_kwargs):
        raise AssertionError('route must not revalidate source frontier candidates')

    # The source frontier already validates its candidates. The L2 scorer
    # evaluates the selected talent-adjusted actor; this is NOT a native PASS.
    monkeypatch.setattr(route, 'validate_talent_selection',
                        redundant_validation, raising=False)
    assert route._source_successors(ir, None, level=10, max_children=2)

    checked_levels = []
    original = route.validate_level_state

    def count_initial_state_checks(state):
        checked_levels.append(state.level)
        return original(state)

    monkeypatch.setattr(route, 'validate_level_state', count_initial_state_checks)
    result = route.search_source_bounded_level_route(
        class_key='druid', start_level=10, end_level=11,
        max_active_paths=1, max_children_per_path=2,
        max_l2_per_state=8, max_total_events=6000)
    assert result['last_contiguous_level'] == 11, result['failures']
    # Later steps are checked by validate_level_transition, which already
    # validates both parent and child. Avoid a third GameIR rebuild.
    assert checked_levels and set(checked_levels) == {10}


def test_route_compute_cap_not_promoted_to_complete():
    result=search_source_bounded_level_route(class_key='druid',start_level=10,
        end_level=13,max_active_paths=1,max_children_per_path=2,
        max_l2_per_state=6,max_total_l2_attempts=6,max_total_events=800)
    assert result['status']=='PARTIAL_BOUNDED_SOURCE_SCENARIO'
    assert result['last_contiguous_level'] in (None,10)
    assert result['compute']['l2_attempts']<=6
    assert result['compute']['event_transitions']<=800
    assert result['full_route_complete'] is False
