import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'wf_gate.py'
spec = importlib.util.spec_from_file_location('wf_gate', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def write(tmp, cl, lv, gate, **kw):
    p = tmp / cl / f'L{lv}' / 'unrestricted' / f'{gate}.json'
    p.parent.mkdir(parents=True, exist_ok=True)
    obj = {'class':cl,'level':lv,'spec':'unrestricted','gate':gate,
           'source_id':'canonical-db-sha', 'engine_id':'engine-sha','scenario_id':'encounter-sha', **kw}
    p.write_text(json.dumps(obj))
    return p


def test_p2_ignores_forged_evidence_and_runs_live(tmp_path,capsys):
    # A superficially perfect imported JSON report must never certify P2.
    write(tmp_path,'druid',20,'P2',structurally_reachable_ranks=42,
          ranks_with_executed_behavior_tests=42,ranks_with_executor_paths=42,
          missing_executor_ranks=[],failed_behavior_ranks=[],talent_paths_legal=True,
          ranks_represented_in_search=42,unlocked_actions_available_to_generated_search=True,
          obsolete_semantic_verification_labels=['partial','unknown'])
    assert mod.main(['--class','druid','--level','20','--gate','P2',
                     '--evidence-dir',str(tmp_path)]) == 1
    output=json.loads(capsys.readouterr().out)
    assert output['status']=='FAIL'
    assert output['results'][0]['pass_count']<output['results'][0]['reachability_count']
    assert any('BEHAVIOR_TEST_MISSING' in x for x in output['results'][0]['reasons'])


def test_p2_live_reports_true_missing_behavior(tmp_path,capsys):
    write(tmp_path,'druid',30,'P2',structurally_reachable_ranks=129,
          ranks_with_executed_behavior_tests=129,ranks_with_executor_paths=129,
          missing_executor_ranks=[],failed_behavior_ranks=[],talent_paths_legal=True)
    assert mod.main(['--class','druid','--level','30','--gate','P2',
                     '--evidence-dir',str(tmp_path)]) == 1
    reasons=json.loads(capsys.readouterr().out)['results'][0]['reasons']
    assert any('IMPLEMENTATION_MISSING' in x for x in reasons)
    assert not any('SEMANTICS_UNVERIFIED' in x for x in reasons)


def test_json_can_be_diagnosed_but_never_certifies_live_p4_p5_p6(tmp_path,capsys):
    common=dict(unlock_coverage_pass=True,talent_gear_apl_jointly_searched=True,
                full_legal_builds=True,complete_100mob_replays=4,mob_count=100)
    write(tmp_path,'druid',30,'P4', search_wall_s=29.8, unique_full_builds=100,
          best_full_s_per_mob=12.6,**common)
    write(tmp_path,'druid',30,'P5', search_wall_s=299.8, unique_full_builds=1200,
          best_full_s_per_mob=12.5,**common)
    write(tmp_path,'druid',30,'P6', s_per_mob_30=12.6, s_per_mob_300=12.5,
          independent_replays_same_scenario=True)
    # Historical validator tests schema consistency, not provenance/execution.
    p4=mod.evaluate(tmp_path,'druid',30,'unrestricted','P4',{})
    p5=mod.evaluate(tmp_path,'druid',30,'unrestricted','P5',{'P4':p4})
    assert p4['status']=='PASS' and p5['status']=='PASS'
    # Critically: the public acceptance CLI refuses to accept these JSONs.
    assert mod.main(['--class','druid','--level','30','--gate','P6',
                     '--evidence-dir',str(tmp_path)]) == 1
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='BLOCKED'
    assert result['results'][0]['reasons'][0].startswith('LIVE_GATE_RUNNER_MISSING')


def test_all_reports_real_gate_names_and_missing_live_providers(tmp_path,monkeypatch,capsys):
    # Do not run expensive real source probes when testing only group dispatch.
    monkeypatch.setattr(mod,'_run_live_gate',
        lambda root,cl,lv,sp,g,scenario: {
            'status':'BLOCKED','reasons':['LIVE_GATE_RUNNER_MISSING:'+g]})
    assert mod.main(['--class','warlock','--level','20','--gate','all',
                     '--evidence-dir',str(tmp_path)]) == 1
    data=json.loads(capsys.readouterr().out)
    assert len(data['results'])==11
    assert [x['gate'] for x in data['results']]==list(mod.GATES)
    assert data['status']=='BLOCKED'


def test_legacy_p7_json_is_never_current_p7_acceptance(tmp_path,capsys):
    common=dict(legacy_winner_full_configuration_replayed_in_new_engine=True,
                both_configurations_same_100mob_scenario=True,
                legacy_winner_on_new_engine_s_per_mob=17.2)
    write(tmp_path,'mage',20,'P7',new_winner_on_new_engine_s_per_mob=16.8,**common)
    assert mod.evaluate(tmp_path,'mage',20,'unrestricted','P7',{})['status']=='PASS'
    assert mod.main(['--class','mage','--level','20','--gate','P7',
                     '--evidence-dir',str(tmp_path)]) == 1
    output=json.loads(capsys.readouterr().out)
    assert output['status']=='BLOCKED'
    assert [r['gate'] for r in output['results']]==[f'P7.{i}' for i in range(1,6)]
