"""P2 rank delta -> actual paid joint optimiser priority, generic and fail-closed."""
from copy import deepcopy
from pathlib import Path
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint, evaluate_p2
from src.game.data.forever.source_checkpoint_p2_optimizer import (
    rank_opportunity_frontier, proposal_l0_opportunity)
from src.v2.source_action_proxy import checkpoint_action_proxy_coverage
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents

SOURCE=Path('evidence/wf336/druid_l20_talent_rank_observations_70338.json')

@pytest.fixture(scope='module')
def inputs():
    ir=build_game_ir_slice(class_key='druid',level=20)
    certificate=evaluate_p2(ir,P2Checkpoint('druid',20),source_observations_path=SOURCE)
    return ir,certificate


def test_all_legal_talent_ranks_are_scored_not_just_l2_executable(inputs):
    ir, cert=inputs
    f=rank_opportunity_frontier(cert,class_key='druid',level=20)
    assert cert['p2_pass']
    assert (f['rank_count'],f['families'],f['source_only_count'])==(69,26,12)
    assert f['ready']
    assert len({(r['talent_id'],r['rank']) for r in f['ranks']})==69
    assert all(r['comparison_unit']=='within_effect_domain_not_seconds_per_mob' for r in f['ranks'])


def test_rank_on_off_is_incremental_and_source_sensitive(inputs):
    ir,cert=inputs
    base=rank_opportunity_frontier(cert,class_key='druid',level=20)
    one=proposal_l0_opportunity(base,{}, {'ferocity':1})
    two=proposal_l0_opportunity(base,{'ferocity':1},{'ferocity':2})
    assert len(one['changes'])==len(two['changes'])==1
    assert one['l0_opportunity']>0 and two['l0_opportunity']>0
    assert not one.get('s_per_mob') and one['not_s_per_mob']
    # Source rank curve numerically influences candidate prior, not just labels.
    changed=deepcopy(cert)
    row=next(x for x in changed['rank_rows'] if x['talent_id']=='ferocity' and x['rank']==1)
    row['l0_effects'][0]['sourced_value']*=0.5
    if 'context_l0_value' in row['l0_effects'][0]:
        row['l0_effects'][0]['context_l0_value']*=0.5
    f2=rank_opportunity_frontier(changed,class_key='druid',level=20)
    assert proposal_l0_opportunity(f2,{}, {'ferocity':1})['l0_opportunity'] != one['l0_opportunity']
    with pytest.raises(ValueError,match='UNSCORED_ALLOCATION'):
        proposal_l0_opportunity(base,{}, {'nonexistent_talent':1})


def test_wrong_checkpoint_or_missing_rank_rejected(inputs):
    ir,cert=inputs
    with pytest.raises(ValueError,match='UNVERIFIED_CHECKPOINT'):
        rank_opportunity_frontier(cert,class_key='warrior',level=20)
    changed=deepcopy(cert)
    changed['rank_rows']=[x for x in changed['rank_rows'] if not(x['talent_id']=='ferocity' and x['rank']==2)]
    with pytest.raises(ValueError,match='MISSING_PREVIOUS_RANK'):
        rank_opportunity_frontier(changed,class_key='druid',level=20)
    wrong=deepcopy(cert); wrong['p2_pass']=False
    with pytest.raises(ValueError,match='UNVERIFIED_CHECKPOINT'):
        rank_opportunity_frontier(wrong,class_key='druid',level=20)


def test_generic_action_proxy_no_missing_module_and_unknown_roles_remain(inputs):
    ir,cert=inputs
    p=checkpoint_action_proxy_coverage(ir,level=20)
    assert p['action_count']==len(ir.actions)
    assert len({x['action_id'] for x in p['ir_actions']})==len(ir.actions)
    assert all(x['unknown_roles_are_not_pruned'] for x in p['ir_actions'])
    with pytest.raises(ValueError,match='MISMATCH'):
        checkpoint_action_proxy_coverage(ir,level=30)


def test_production_paid_joint_uses_69_source_ranks_for_l0_order(inputs):
    ir,cert=inputs
    result=run_source_budgeted_joint_talents(class_key='druid',level=20,
        max_evaluations=40,evaluations_per_talent=10,initial_search=5,
        search_per_gear=5,max_gear_states=1,ir_slice=ir,
        talent_l0_certificate=cert)
    assert result['attempted']==result['evaluated']+result['blocked']==40
    assert result['talent_l0_source_ranks_scored']==69
    assert result['talent_l0_source_only_ranks_scored']==12
    assert len(result['talent_l0_rank_frontier'])==69
    assert sum(not r['l2_supported'] for r in result['talent_l0_rank_frontier'])==12
    assert result['talent_l0_priority_queries']>0
    assert result['talent_l0_influenced_candidate_order']
    # The prefix backend charges paid attempts; its event meter is not yet
    # populated in the enclosing joint result (not a P2 criterion).
    assert result['evaluated']>0 and result['distinct_talent_allocations_paid_L2']>1
    assert result['complete_search'] is False
    assert result['winner'] is not None
