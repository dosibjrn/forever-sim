import copy,hashlib,json,sys
from pathlib import Path
import pytest
TOOLS=Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0,str(TOOLS))
from wf_gate_import_search import import_search,build_p6
from wf_gate_engine_fingerprint import runtime_fingerprint,_RUNTIME_MODULES


def artifact(tmp, budget=30):
    for part in _RUNTIME_MODULES:
        file=tmp/part
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text('source code of '+part+'\n')
    db=tmp/'source.sqlite';db.write_bytes(b'pretend sqlite for digest test')
    scenario={'class':'druid','level':30,'enemy':{'health':955},'pack_size':2,
              'bonus_talent_points':5,'incoming_attacks':[{'hits':True}],
              'mitigation_rules':[],'100mob_replay':True,'recovery_paid':True}
    sid=hashlib.sha256(json.dumps(scenario,sort_keys=True).encode()).hexdigest()
    config={'equipped_gear':{'head':'123'},'allocation':{'ferocity':5},
            'policy_ir':{'id':'x','rules':[{'action_id':'claw'}]},
            'recovery':'always','opening_action_ids':['claw'],'policy_signature':'a'}
    raw={'schema':'wf463_spec_100mob_v1','checkpoint':'druid:L30:feral',
         'source_sha256':hashlib.sha256(db.read_bytes()).hexdigest(),
         'engine_id':runtime_fingerprint(tmp),'scenario_id':sid,'scenario_payload':scenario,
         'spec_constraint':{'tree_key':'feral','minimum_points':21,'required_combat_mode':'cat'},
         'bonus_talent_points':5,'search_budget':budget,'gear_role':'druid_feral',
         'search_wall_s':29.854 if budget==30 else 299.793,
         'unique':219 if budget==30 else 2693,
         'shortlist':[config],
         'joint_axis_paid_coverage':{'distinct_talent_allocations':4,'distinct_gear_configs':3,
            'distinct_policy_signatures':7,'distinct_recovery_policies':2,'paid_screens':200},
         'validation':{'status':'SHORTLIST_RANKING_CONFIRMED','100mob_replays':1,
            'complete_100mob_replays':1,'validation_outside_search_budget':True,
            'rows':[{'id':'0','status':'COMPLETE','count':100,
                     'full_s_per_mob':19.795824 if budget==30 else 19.731693}]},
         'unlock_coverage_pass':False,
         'unlock_coverage':{'primal_bite':{'complete_paid_screens':0,'status':'NOT_EXECUTED_P4_BLOCKED'}}}
    return raw,db


def test_real_search_import_exposes_cat_unlock_failure(tmp_path):
    raw,db=artifact(tmp_path)
    x=import_search(raw,cls='druid',level=30,spec='feral-cat',gate='P4',db=db,checkout=tmp_path)
    assert x['unique_full_builds']==219
    assert x['best_full_s_per_mob']==19.795824
    assert x['unlock_coverage_pass'] is False
    assert x['uncovered_unlock_families']==['primal_bite']
    from wf_gate import _validate_p4
    errors=_validate_p4(x,{})
    assert 'SOURCE_UNLOCK_UNEXECUTED:primal_bite' in errors


def test_cannot_import_different_engine_code(tmp_path):
    raw,db=artifact(tmp_path)
    (tmp_path/'src/game/runtime/simulator.py').write_text('modified')
    with pytest.raises(ValueError,match='SEARCH_ENGINE_CODE_CHANGED'):
        import_search(raw,cls='druid',level=30,spec='feral-cat',gate='P4',db=db,checkout=tmp_path)


def test_cannot_import_patched_source_or_scenario(tmp_path):
    raw,db=artifact(tmp_path)
    db.write_bytes(b'new db')
    with pytest.raises(ValueError,match='DB_SHA256_DIFFERS'):
        import_search(raw,cls='druid',level=30,spec='feral-cat',gate='P4',db=db,checkout=tmp_path)
    db.write_bytes(b'pretend sqlite for digest test')
    raw['scenario_payload']['enemy']['health']=888
    with pytest.raises(ValueError,match='SCENARIO_DIGEST_MISMATCH'):
        import_search(raw,cls='druid',level=30,spec='feral-cat',gate='P4',db=db,checkout=tmp_path)


def test_30_300_ratio_without_accepting_failed_p4(tmp_path):
    r30,db=artifact(tmp_path,30)
    r300,_=artifact(tmp_path,300)
    d=tmp_path/'gate_evidence/druid/L30/feral-cat'
    d.mkdir(parents=True)
    import_one=lambda r,g: import_search(r,cls='druid',level=30,spec='feral-cat',gate=g,db=db,checkout=tmp_path)
    a,b=import_one(r30,'P4'),import_one(r300,'P5')
    (d/'P4.json').write_text(json.dumps(a))
    (d/'P5.json').write_text(json.dumps(b))
    c=build_p6(tmp_path/'gate_evidence',cls='druid',level=30,spec='feral-cat')
    assert c['numeric_ratio_30_300']==pytest.approx(1.00325,rel=1e-4)
    assert c['independent_replays_same_scenario'] is True
    # Numerical success never masks the P4 unlock witness being absent.
    from wf_gate import evaluate
    previous={}
    for gate in ('P4','P5'):
        previous[gate]=evaluate(tmp_path/'gate_evidence','druid',30,'feral-cat',gate,previous)
        assert previous[gate]['status']=='FAIL'
    (d/'P6.json').write_text(json.dumps(c))
    assert evaluate(tmp_path/'gate_evidence','druid',30,'feral-cat','P6',previous)['status']=='FAIL'


def test_300_report_does_not_reuse_30_budget(tmp_path):
    r,db=artifact(tmp_path,30)
    with pytest.raises(ValueError,match='SEARCH_BUDGET_MISMATCH'):
        import_search(r,cls='druid',level=30,spec='feral-cat',gate='P5',db=db,checkout=tmp_path)


def test_joint_search_not_certified_with_unpaid_gear_axis(tmp_path):
    r,db=artifact(tmp_path)
    r['joint_axis_paid_coverage']['distinct_gear_configs']=1
    with pytest.raises(ValueError,match='JOINT_PAID_TALENT_GEAR_APL_AXIS'):
        import_search(r,cls='druid',level=30,spec='feral-cat',gate='P4',db=db,checkout=tmp_path)
