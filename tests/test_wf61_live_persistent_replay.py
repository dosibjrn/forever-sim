"""Contract-only negative controls for the WF61 live gsim replay tool.

These synthetic rows test rejection only; they are NOT simulated kills.
The Actions workflow runs the separate actual source-backed 1/2/100 replay.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from tools.wf61_live_persistent_replay import load_source_stage, validate_real_replay


def _contract_only(n=2):
    rows=[]
    for i in range(n):
        start=float(i*10)
        rows.append({'mob':i+1,'target_id':f'source_mob_{i+1}',
                     'pull_started_s':start,'kill_finished_s':start+4,
                     'recovery_s':6.,'recovery_finished_s':start+10,
                     'combat_s':4.,'actions':{'source_spell':1}})
    return {'status':'COMPLETE','count':n,'continuous_actor_state':True,
            'source_only':True,'spatial_mode':'2d_sequential_not_simultaneous_pack',
            'events':n,'source_action_counts':{'source_spell':n},
            'total_s':10.*n,'mean_s_per_mob':10.,'combat_s':4.*n,
            'recovery_s':6.*n,'maintenance_s':0.,'spaced_travel_s':0.,'pull_trace':rows,
            'pull_trace_audit':{'status':'GSIM_PERSISTENT_TRACE_INVARIANTS_ONLY',
                                'distinct_targets':n,
                                'native_world_action_ack_verified':False}}


def test_valid_contract_rows_are_not_a_native_certificate():
    assert validate_real_replay(_contract_only(),2)['native_world_action_ack_verified'] is False


@pytest.mark.parametrize('mutation',[
    lambda r:r.update(status='BLOCKED_COMBAT'),
    lambda r:r.update(count=1),
    lambda r:r.update(continuous_actor_state=False),
    lambda r:r.update(source_only=False),
    lambda r:r.update(events=0),
    lambda r:r.update(source_action_counts={}),
    lambda r:r.update(mean_s_per_mob=float('nan')),
    lambda r:r.update(recovery_s=0.),
    lambda r:r['pull_trace_audit'].update(native_world_action_ack_verified=True),
    lambda r:r['pull_trace_audit'].update(distinct_targets=1),
    lambda r:r['pull_trace'][1].update(target_id='source_mob_1'),
    lambda r:r['pull_trace'][1].update(pull_started_s=9.),
    lambda r:r['pull_trace'][1].update(actions={}),
    lambda r:r['pull_trace'][0].update(recovery_finished_s=5.),
])
def test_fabricated_or_incomplete_replay_cannot_be_reported_complete(mutation):
    result=deepcopy(_contract_only());mutation(result)
    with pytest.raises(ValueError,match='WF61_'):
        validate_real_replay(result,2)


def test_source_stage_loader_fingerprints_exact_bytes(tmp_path):
    source=tmp_path/'source.json'
    source.write_text(json.dumps({'winner':{'allocation':{},'gear_policy_result':{'winner':{}}}}))
    stage,sha=load_source_stage(source)
    assert stage['allocation']=={}
    assert len(sha)==64
    source.write_text(source.read_text()+'\n')
    assert load_source_stage(source)[1]!=sha


def test_reject_non_stage_json(tmp_path):
    source=tmp_path/'bad.json'
    source.write_text('{"winner":{"score":123}}')
    with pytest.raises(ValueError,match='WF61_INVALID_SOURCE_STAGE'):
        load_source_stage(source)


@pytest.mark.parametrize('mutation', [
    lambda r: r['source_action_counts'].update(source_spell=3),
    lambda r: r['source_action_counts'].update(unseen_spell=1),
    lambda r: r['source_action_counts'].update(source_spell=True),
    lambda r: r['pull_trace'][1].update(actions={'different_spell': 1}),
    lambda r: r.update(total_s=30., mean_s_per_mob=15.),
    lambda r: r.update(maintenance_s=-1.),
])
def test_source_action_and_clock_aggregate_mismatch_rejected(mutation):
    """Actual per-pull source actions and paid actor clock must agree with totals."""
    result = deepcopy(_contract_only())
    mutation(result)
    with pytest.raises(ValueError, match='WF61_'):
        validate_real_replay(result, 2)
