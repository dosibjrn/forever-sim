"""P1/2/4/... unchanged: quest score is a separate optional paid metric."""
from __future__ import annotations
from pathlib import Path
import pytest
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate
from tools.wf427_druid_l30_quest_horizon import prepared_rows

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def finalists():
    return list(prepared_rows(ROOT/'evidence/wf427/WF427_L30_COLD_FINALISTS.json'))

def test_quest_end_does_not_charge_last_full_recovery(finalists):
    _,_,candidate,_=finalists[0]
    paid=evaluate_persistent_candidate(candidate,level=30,mobs=4,max_total_events=6000,
        settle_final_recovery=True,trace_pulls=True)
    quest=evaluate_persistent_candidate(candidate,level=30,mobs=4,max_total_events=6000,
        settle_final_recovery=False,trace_pulls=True)
    assert paid['status']==quest['status']=='COMPLETE'
    assert len(quest['pull_trace'])==4
    assert paid['pull_trace'][-1]['full_recovery']
    assert not quest['pull_trace'][-1]['full_recovery']
    assert quest['pull_trace'][-1]['recovery_s']==0
    assert quest['total_s']<paid['total_s']
    assert abs(quest['total_s']-sum(x['combat_s']+x['recovery_s'] for x in quest['pull_trace'])-quest['maintenance_s'])<1e-6
    assert quest['final_resources']['mana']<paid['final_resources']['mana']

def test_water_timing_trace_and_cooldown_provenance(finalists):
    _,_,candidate,_=finalists[0]
    r=evaluate_persistent_candidate(candidate,level=30,mobs=8,max_total_events=8000,
        settle_final_recovery=False,trace_pulls=True)
    assert r['status']=='COMPLETE'
    pull=r['pull_trace']
    assert len(pull)==8
    assert [p['mob'] for p in pull]==list(range(1,9))
    assert pull[-1]['recovery_s']==0.0
    assert sum(p['water_s'] for p in pull)>0
    assert pull[-1]['water_s']==0
    assert all(p['water_s'] <= p['recovery_s']+1e-7 for p in pull)
    assert all(isinstance(p['long_cooldowns_used'],dict) and isinstance(p['long_cooldowns_not_ready_at_kill'],dict)
               for p in pull)
    assert sum(p['actions'].get('insect_swarm:24974',0) for p in pull)==r['source_action_counts']['insect_swarm:24974']

def test_default_100_mob_metric_unchanged(finalists):
    _,row,candidate,_=finalists[0]
    result=evaluate_persistent_candidate(candidate,level=30,mobs=100,max_total_events=200000)
    assert result['status']=='COMPLETE'
    assert abs(result['mean_s_per_mob']-row['seconds_per_mob'])<1e-9
    assert result['events']==row['full_events']
    assert result['settle_final_recovery'] is True


def test_2d_quest_requires_real_2d_endpoint_engine(finalists):
    _,_,candidate,_=finalists[0]
    with pytest.raises(ValueError,match='QUEST_HORIZON_SEQUENTIAL_ONLY'):
        evaluate_persistent_candidate(candidate,level=30,mobs=2,pack_size=2,settle_final_recovery=False)
