"""A sourced gear alternative may lose a 2-mob screen and win 100 mobs."""
import json
from pathlib import Path

from src.v2.source_persistent_gear_neighborhood import refine_source_gear_persistent
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate

ROOT=Path(__file__).resolve().parents[1]


def test_bounded_neighborhood_derives_source_gear_without_old_winner_item_ids():
    # Source-only old seed is a *test input*, not used by the production search.
    stage=json.loads((ROOT/'WF299_DRUID_L20_30S_BLIND_EVIDENCE.json').read_text())['winner']
    before=evaluate_persistent_candidate(prepare_candidate(class_key='druid',level=20,stage=stage),
                                         level=20,mobs=100)
    assert before['status']=='COMPLETE'
    r=refine_source_gear_persistent(class_key='druid',level=20,stage=stage,
                                   max_proposals=24,max_finalists=5)
    assert r['status']=='PERSISTENT_GEAR_NEIGHBOR_VERIFIED_BOUNDED'
    assert r['distinct_source_gear_sets_evaluated']>0
    assert r['screen_mobs']==10 and r['finalist_mobs']==100
    best=r['winner']
    assert best['persistent']['status']=='COMPLETE'
    assert best['persistent']['mean_s_per_mob']<before['mean_s_per_mob']-.5
    # No fixed item choices: every winner item came from current source selector.
    assert all(i['required_level_origin']=='observed' and i['required_level']<=20
               for i in best['stage']['gear_policy_result']['winner']['gear']['slots'].values())
    assert not r['global_optimum_proven'] and not r['formal_checkpoint_accepted']


def test_source_gear_neighborhood_has_finite_budget_validation():
    import pytest
    stage=json.loads((ROOT/'WF299_DRUID_L20_30S_BLIND_EVIDENCE.json').read_text())['winner']
    with pytest.raises(ValueError,match='budget'):
        refine_source_gear_persistent(class_key='druid',level=20,stage=stage,max_proposals=0)
