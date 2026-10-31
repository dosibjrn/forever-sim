"""WF360: strict six-gate budget semantics, legal build identity and evidence."""
import json
from pathlib import Path
from unittest.mock import patch
import subprocess
import pytest
from tools.wf360_l30_checkpoint_deadline import run
from tools.wf360_l30_p4_worker import identity, RECOVERY


def _stage(item_id=123, rank=1):
    return {'allocation':{'ferocity':rank},'gear_policy_result':{'winner':{
        'gear':{'slots':{'weapon':{'item_id':item_id}}},
        'winner':{'prefix':['cat_form:768'],'fallback':'claw:1082',
                  'guarded_action':None,'guarded_conditions':[]}}}}


def test_unique_identity_uses_talent_gear_and_policy():
    x=_stage()
    assert identity(x)==identity(json.loads(json.dumps(x)))
    assert identity(x)!=identity(_stage(item_id=124))
    assert identity(x)!=identity(_stage(rank=2))
    y=_stage();y['gear_policy_result']['winner']['winner']['fallback']='wrath:5176'
    assert identity(x)!=identity(y)


def test_contract_only_30_or_300(tmp_path):
    with pytest.raises(ValueError,match='ONLY_CONTRACT'):
        run(output=tmp_path/'x.json',deadline_s=60.,evaluations=1,events=1,screens=1,finalists=1)


def test_timeout_cannot_leave_false_acceptance(tmp_path):
    output=tmp_path/'x.json';output.write_text('STALE')
    with patch('tools.wf360_l30_checkpoint_deadline.subprocess.run',side_effect=subprocess.TimeoutExpired('worker',30)):
        r=run(output=output,deadline_s=30.,evaluations=1,events=1,screens=1,finalists=1)
    assert r['status']=='FAIL_DEADLINE' and not output.exists()


def test_crash_cannot_leave_false_acceptance(tmp_path):
    output=tmp_path/'x.json'
    with patch('tools.wf360_l30_checkpoint_deadline.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','ERROR')):
        r=run(output=output,deadline_s=30.,evaluations=1,events=1,screens=1,finalists=1)
    assert r['status']=='FAIL_WORKER' and not output.exists()


def test_p4_independent_measured_evidence():
    p=Path(__file__).resolve().parents[1]/'evidence/wf360/WF360_L30_P4_30S.json'
    if not p.exists():pytest.skip('measured P4 evidence not yet available')
    x=json.loads(p.read_text())
    assert x['checkpoint']=='druid:L30:unrestricted'
    assert x['status']=='PASS' and x['independent_discovery'] and not x['old_winner_seeded']
    assert x['end_to_end_wall_s']<=30
    assert x['unique_complete_builds_paid_lower_bound']>=1
    assert x['winner']['actual_100mob_s_per_mob']>0
    assert x['winner']['predicted_100mob_s_per_mob']>0
    assert x['recovery_policy']['health_fraction']==RECOVERY.health_fraction
    assert x['recovery_policy']['mana_fraction']==RECOVERY.mana_fraction


def test_p5_more_distinct_legal_builds_and_same_source():
    root=Path(__file__).resolve().parents[1]
    a=json.loads((root/'evidence/wf360/WF360_L30_P4_30S.json').read_text())
    b=json.loads((root/'evidence/wf360/WF360_L30_P5_300S.json').read_text())
    assert a['source_db_sha256']==b['source_db_sha256']
    assert a['recovery_policy']==b['recovery_policy']
    assert b['end_to_end_wall_s']<=300
    assert b['unique_complete_builds_paid_lower_bound']>a['unique_complete_builds_paid_lower_bound']
    assert b['attempts_total']>a['attempts_total']
    assert b['events_total']>a['events_total']


def test_p6_two_fresh_hundred_mob_replays():
    p=Path(__file__).resolve().parents[1]/'evidence/wf360/WF360_L30_P6_FRESH_100MOB.json'
    x=json.loads(p.read_text())
    assert x['status']=='PASS'
    assert x['p4_replay']['status']==x['p5_replay']['status']=='COMPLETE'
    assert x['p4_replay']['count']==x['p5_replay']['count']==100
    assert x['t30_s_per_mob']<=1.01*x['t300_s_per_mob']
    assert x['global_optimality_proven'] is False
