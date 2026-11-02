"""W3 real runtime acceptance: source talent -> fresh gear -> ordered combat/recovery."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_frontier import source_legal_talent_neighbors
from src.game.talents import validate_talent_selection
from src.v2.source_budgeted_joint_talents import run_source_budgeted_joint_talents
from tools.wf260_run_budgeted_joint import run


def test_source_frontier_has_rank_sweeps_transfers_and_no_illegal_states():
    ir=build_game_ir_slice(class_key='mage',level=20)
    root=source_legal_talent_neighbors(ir,{},level=20)
    assert root['source_talent_families']==54
    assert root['executable_talent_families']==4
    assert len(root['unsupported_talent_ids'])==50
    assert any(n.operation=='rank_sweep' and dict(n.allocation)=={'improved_frostbolt':5}
               for n in root['neighbors'])
    after=source_legal_talent_neighbors(ir,{'improved_frostbolt':5},level=20)
    assert any(n.operation=='rank_sweep' and dict(n.allocation)=={
        'improved_frostbolt':5,'elemental_precision':5} for n in after['neighbors'])
    assert any(n.operation=='point_transfer' for n in after['neighbors'])
    for row in (*root['neighbors'],*after['neighbors']):
        validate_talent_selection(ir,dict(row.allocation),level=20)
        assert set(dict(row.allocation)).isdisjoint(root['unsupported_talent_ids'])
    assert all('ice_lance' not in dict(n.allocation) for n in root['neighbors'])


def test_druid_l10_real_talent_change_restarts_full_gear_policy():
    r=run('druid',10,160,80)
    assert r['status']=='EVALUATED_BOUNDED'
    assert r['attempted']==160==r['evaluated']+r['blocked']
    assert len(r['best_vs_budget'])==160
    assert [x['attempt'] for x in r['best_vs_budget']]==list(range(1,161))
    base,improved=r['stages']
    assert base['allocation']=={}
    assert improved['allocation']=={'improved_wrath':1}
    assert improved['score_s_per_mob']<base['score_s_per_mob']
    assert improved['source_context_sha256']!=base['source_context_sha256']
    for stage in (base,improved):
        nested=stage['gear_policy_result']['stages']
        assert len(nested)>=3
        assert nested[0]['stage']=='source_naked'
        assert nested[1]['stage']=='named_gear_1'
        assert nested[0]['search_is_fresh_from_source_singles_pairs']
        assert nested[1]['search_is_fresh_from_source_singles_pairs']
        assert nested[0]['context_sha256']!=nested[1]['context_sha256']
        assert stage['gear_policy_result']['winner']['gear']['slots']['weapon']['item_id']>0
    assert r['winner']['score_s_per_mob']==pytest.approx(11.693946996827993)
    scores=[x['best_s_per_mob'] for x in r['best_vs_budget'] if x['best_s_per_mob'] is not None]
    assert scores==sorted(scores,reverse=True)
    assert scores[0]>scores[-1]


def test_mage_l20_live_adaptive_selection_heldout_and_budget():
    r=run('mage',20,480,80,heldout=True)
    assert r['attempted']==479
    assert r['total_real_simulator_attempts']==480
    assert r['blocked']==0 and r['evaluated']==479
    assert len(r['stages'])==6
    assert r['legal_talent_states_discovered']>len(r['stages'])
    assert r['winner']['allocation']=={'improved_frostbolt':5,'elemental_precision':5}
    assert r['winner']['score_s_per_mob']==pytest.approx(13.688288288288286)
    assert r['stages'][4]['parent_allocation']=={'improved_frostbolt':5}
    assert r['stages'][5]['parent_allocation']=={'improved_frostbolt':5}
    assert all(s['fresh_gear_and_policy_search'] for s in r['stages'])
    assert len({s['source_context_sha256'] for s in r['stages']})==6
    assert all(s['gear_policy_result']['named_gear_states_evaluated']>=1 for s in r['stages'])
    challenger=r['heldout_challenger']
    assert challenger['evaluated_independently']
    assert challenger['same_named_gear_as_new_winner']
    assert challenger['seconds_per_mob']==pytest.approx(r['winner']['score_s_per_mob'])
    assert challenger['valid_full_OG_comparison'] is False


def test_negative_invalid_allocation_and_mismatched_ir_fail_closed():
    with pytest.raises(ValueError,match='unknown talent'):
        run_source_budgeted_joint_talents(class_key='mage',level=20,
            max_evaluations=1,initial_allocation={'invented':1})
    with pytest.raises(ValueError,match='tier gate'):
        run_source_budgeted_joint_talents(class_key='mage',level=20,
            max_evaluations=1,initial_allocation={'ice_lance':1})
    with pytest.raises(ValueError,match='mismatch'):
        run_source_budgeted_joint_talents(class_key='mage',level=20,
            max_evaluations=1,ir_slice=build_game_ir_slice(class_key='druid',level=20))
    with pytest.raises(ValueError,match='positive'):
        run_source_budgeted_joint_talents(class_key='mage',level=20,max_evaluations=0)


def test_tiny_budget_charges_exact_one_real_runtime_call():
    r=run_source_budgeted_joint_talents(class_key='druid',level=10,
        max_evaluations=1,evaluations_per_talent=80)
    assert r['attempted']==1
    assert r['evaluated']+r['blocked']==1
    assert r['talent_states_evaluated']==1
    assert r['unspent_budget']==0


def test_source_revision_changes_talent_and_gear_context():
    ir=build_game_ir_slice(class_key='druid',level=10)
    changed=replace(ir,actor=replace(ir.actor,metadata={**ir.actor.metadata,
        'source_build_revision':'wf260_test_revision'}))
    a=run_source_budgeted_joint_talents(class_key='druid',level=10,
        max_evaluations=1,ir_slice=ir)
    b=run_source_budgeted_joint_talents(class_key='druid',level=10,
        max_evaluations=1,ir_slice=changed)
    assert a['source_context_sha256']!=b['source_context_sha256']
    assert a['stages'][0]['source_context_sha256']!=b['stages'][0]['source_context_sha256']
