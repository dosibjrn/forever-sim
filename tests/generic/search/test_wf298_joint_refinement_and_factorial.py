"""One real L2 correctness regression: cross-talent source search and held-out oracle."""
from __future__ import annotations
import copy
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_joint_local_refinement import refine_named_gear_talents
from tools.wf298_druid_l20_verified_delta import run, ARGS

@pytest.fixture(scope='module')
def proof():
    return run()

def test_blind_source_search_really_improves_and_is_budgeted(proof):
    assert proof['heldout_was_not_a_search_seed']
    assert proof['independent_search_attempts']<=ARGS['max_evaluations']
    assert proof['independent_search_events']<=ARGS['max_event_transitions']
    assert proof['refinement']['attempted']==proof['refinement']['evaluated']+proof['refinement']['blocked']
    assert proof['refinement']['visited_legal_allocations']>=20
    assert proof['refinement']['fixed_policy_improvement_s']>0.2
    assert proof['refinement']['fresh_policy_winner'] is not None
    assert proof['independent_search_winner']['policy_freshly_searched_after_refinement']
    assert proof['new_minus_old_s_per_mob'] < -1.0
    assert proof['validated_checkpoints_delta']==0

def test_counterfactual_same_exact_runtime_and_factorial(proof):
    assert all(proof['all_four_policy_equivalence_checks'].values())
    assert abs(proof['gear_effect_shapley_s_per_mob']+
               proof['talent_effect_shapley_s_per_mob']+
               proof['policy_effect_s_per_mob']-proof['new_minus_old_s_per_mob'])<1e-9
    cells=proof['factorial_eight_fresh_L2_replays']
    assert len(cells)==8
    assert all(row['kill_s']+row['recovery_s']==pytest.approx(row['score_s_per_mob']) for row in cells.values())
    assert cells['old_gear__old_talent__old_policy']['kill_s']==13
    assert cells['new_gear__new_talent__new_policy']['kill_s']==12

def test_cross_talent_negative_gear_legality_and_hard_budgets(proof):
    ir=build_game_ir_slice(class_key='druid',level=20)
    w=copy.deepcopy(proof['independent_search_winner'])
    first=next(iter(w['gear_policy_result']['winner']['gear']['slots'].values()))
    first['required_level']=21
    with pytest.raises(ValueError,match='nonobserved or over-level'):
        refine_named_gear_talents(ir=ir,class_key='druid',level=20,
            incumbent=w,max_l2_attempts=6,max_event_transitions=500,
            reserve_fresh_policy_attempts=2)
    with pytest.raises(ValueError,match='fresh policy reserve'):
        refine_named_gear_talents(ir=ir,class_key='druid',level=20,
            incumbent=proof['independent_search_winner'],max_l2_attempts=3,
            max_event_transitions=500,reserve_fresh_policy_attempts=3)
