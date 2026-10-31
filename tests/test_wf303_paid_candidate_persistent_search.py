"""WF303: paid L2 cross-talent candidates must reach persistent objective.

The optimizer never reads these regression fixtures. They are held-out
replays of two independently observed source-derived legal configurations.
"""
from copy import deepcopy
import json
from pathlib import Path

from src.v2.source_persistent_joint_finalists import (
    _paid_source_candidate_stages, evaluate_persistent_candidate,
    prepare_candidate, select_persistent_finalists,
)

ROOT=Path(__file__).resolve().parents[1]


def old_stage():
    return json.loads((ROOT/'WF299_DRUID_L20_30S_BLIND_EVIDENCE.json').read_text())['winner']


def paid_stage():
    return json.loads((ROOT/'WF303_BEST_COLD_PAID_CANDIDATE.json').read_text())


def refinement_from_actual_paid_evidence(stage):
    return {'fixed_named_gear':stage['gear_policy_result']['winner']['gear'],
            'fixed_policy_record':stage['gear_policy_result']['winner']['winner'],
            'observations':[{'allocation':stage['allocation'],
                             'score_s_per_mob':stage['score_s_per_mob'],
                             'status':'FULL_L2_FIXED_POLICY'}]}


def test_paid_l2_refinement_is_evaluated_and_reranked_under_current_source_runtime():
    old=old_stage();new=paid_stage()
    joint={'stages':[old], 'post_talent_refinement':refinement_from_actual_paid_evidence(new)}
    result=select_persistent_finalists(class_key='druid',level=20,joint_result=joint,
                                      max_screen_candidates=2,max_finalists=2)
    assert result['joint_stages']==1
    assert result['paid_candidate_stages']==2
    assert result['screen_evaluated']==result['finalists_evaluated']==2
    origins={x['stage'].get('paid_candidate_origin') for x in result['finalists']}
    assert 'paid_refinement_fixed_policy' in origins  # source-paid challenger is not dropped
    assert result['winner']['persistent']['mean_s_per_mob']==min(
        x['persistent']['mean_s_per_mob'] for x in result['finalists'])
    assert result['winner']['persistent']['maintenance_casts']==4
    assert abs(result['winner']['persistent']['mean_s_per_mob']-13.449219927138392)<1e-9
    assert not result['global_optimum_proven']


def test_one_mob_stage_estimate_is_not_equal_to_new_upkeep_objective():
    stage=paid_stage()
    candidate=prepare_candidate(class_key='druid',level=20,stage=stage)
    result=evaluate_persistent_candidate(candidate,level=20,mobs=1)
    assert result['status']=='COMPLETE'
    assert abs(result['mean_s_per_mob']-stage['score_s_per_mob'])>0.1
    assert result['maintenance_casts']==2  # Mark + Thorns charged in the same L2/L3 runtime
    assert result['events']>0


def test_blocked_unpaid_and_nonfinite_refinement_never_enters_candidate_set():
    paid=paid_stage();ref=refinement_from_actual_paid_evidence(paid)
    ref['observations'][0]['status']='BLOCKED_L2'
    ref['observations'].append({'allocation':paid['allocation'],
         'score_s_per_mob':None,'status':'FULL_L2_FIXED_POLICY'})
    stages=_paid_source_candidate_stages({'stages':[old_stage()],
                                           'post_talent_refinement':ref})
    assert len(stages)==1
    assert stages[0]['allocation']==old_stage()['allocation']


def test_parent_fixed_challenger_is_reused_not_claimed_fresh():
    new=paid_stage();gear=new['gear_policy_result']['winner']['gear']
    policy=new['gear_policy_result']['winner']['winner']
    joint={'stages':[old_stage()], 'fixed_policy_challengers':[
        {'allocation':new['allocation'],'score_s_per_mob':new['score_s_per_mob'],
         'parent_named_gear':gear,'parent_policy':policy}]}
    stages=_paid_source_candidate_stages(joint)
    assert len(stages)==2
    assert stages[-1]['source_policy_and_gear_reused']
    result=select_persistent_finalists(class_key='druid',level=20,
        joint_result=joint,max_screen_candidates=2,max_finalists=2)
    assert any(x['stage'].get('paid_candidate_origin')=='paid_parent_fixed_policy' for x in result['finalists'])
    assert result['winner']['persistent']['mean_s_per_mob']==min(
        x['persistent']['mean_s_per_mob'] for x in result['finalists'])


def test_illegal_paid_refinement_is_not_silently_legalized():
    new=paid_stage();illegal=deepcopy(new)
    illegal['allocation']={'not_a_source_talent':100}
    joint={'stages':[old_stage()],
           'post_talent_refinement':refinement_from_actual_paid_evidence(illegal)}
    result=select_persistent_finalists(class_key='druid',level=20,
        joint_result=joint,max_screen_candidates=2,max_finalists=2)
    assert result['paid_candidate_stages']==2
    assert result['screen_evaluated']==2
    assert result['screen_completed']==1
    assert result['winner']['allocation']==old_stage()['allocation']
    assert any(x['screen']['status']=='BLOCKED_CANDIDATE' for x in result['screening'])
