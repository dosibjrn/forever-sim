"""Regression: gate authority comes from running code, never from hand-written JSON."""
import json
from types import SimpleNamespace

from tools import wf_gate


def _forged_json(tmp_path, gate, **values):
    path = tmp_path / 'druid' / 'L60' / 'balance' / f'{gate}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'class': 'druid', 'level': 60,
                                'spec': 'balance', 'gate': gate,
                                'status': 'PASS', 'source_id': 'forged',
                                'engine_id': 'forged',
                                'search_wall_s': 300,
                                'all_top5_items_source_legal': True,
                                **values}))
    return path


def test_forged_p3_json_does_not_certify(tmp_path, capsys):
    _forged_json(tmp_path, 'P3')
    assert wf_gate.main(['--class','druid','--level','60','--spec','balance',
                         '--gate','P3','--evidence-dir',str(tmp_path)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'BLOCKED'
    assert report['results'][0]['reasons'] == [
        'LIVE_GATE_RUNNER_MISSING:tools.wf_gate_p3_live']


def test_forged_p75_json_does_not_certify(tmp_path, capsys):
    _forged_json(tmp_path, 'P7.5', dps=9000, acceptance='PASS')
    assert wf_gate.main(['--class','druid','--level','60','--spec','balance',
                         '--gate','P7.5','--evidence-dir',str(tmp_path)]) == 1
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='BLOCKED'
    assert report['results'][0]['gate']=='P7.5'


def test_real_code_provider_is_invoked_not_evidence(tmp_path, monkeypatch, capsys):
    _forged_json(tmp_path, 'P4', search_wall_s=30)
    called = []
    def run_live(root, class_key, level, *, spec):
        called.append((root, class_key, level, spec))
        return {'status':'FAIL', 'reasons':['ACTUAL_RUNTIME_REPLAY_FAILED']}
    original = wf_gate.importlib.import_module
    def load(name):
        if name == 'tools.wf_gate_p4_live':
            return SimpleNamespace(run_live=run_live)
        return original(name)
    monkeypatch.setattr(wf_gate.importlib, 'import_module', load)
    assert wf_gate.main(['--class','druid','--level','60','--spec','balance',
                         '--gate','P4','--evidence-dir',str(tmp_path)]) == 1
    result=json.loads(capsys.readouterr().out)
    assert called == [(wf_gate.ROOT,'druid',60,'balance')]
    assert result['results'][0]['reasons']==['ACTUAL_RUNTIME_REPLAY_FAILED']


def test_runner_cannot_claim_pass_without_runtime_proof(monkeypatch, capsys):
    original = wf_gate.importlib.import_module
    def load(name):
        if name == 'tools.wf_gate_p5_live':
            return SimpleNamespace(run_live=lambda *a,**k:{
                'status':'PASS','reasons':[],'source_id':'LLM-generated'})
        return original(name)
    monkeypatch.setattr(wf_gate.importlib,'import_module',load)
    assert wf_gate.main(['--class','druid','--level','60',
                         '--gate','P5']) == 1
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='FAIL'
    assert report['results'][0]['reasons']==['MISSING_EXECUTED_RUNTIME_PROOF']


def test_live_provider_exceptions_fail_closed(monkeypatch, capsys):
    original=wf_gate.importlib.import_module
    def error(*a, **k):
        raise RuntimeError('combat engine error')
    def load(name):
        if name == 'tools.wf_gate_p7_2_live':
            return SimpleNamespace(run_live=error)
        return original(name)
    monkeypatch.setattr(wf_gate.importlib,'import_module',load)
    assert wf_gate.main(['--class','druid','--level','60',
                         '--gate','P7.2']) == 1
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='FAIL'
    assert 'LIVE_GATE_EXECUTION_FAILED:RuntimeError' in report['results'][0]['reasons'][0]


def test_p7_aggregate_requires_all_five_real_subgates(monkeypatch,capsys):
    called=[]
    def fake(root,cls,lv,spec,gate,scenario):
        called.append(gate)
        return {'status':'BLOCKED','reasons':['NOT_EXECUTED']}
    monkeypatch.setattr(wf_gate,'_run_live_gate',fake)
    assert wf_gate.main(['--class','druid','--level','60','--gate','P7'])==1
    report=json.loads(capsys.readouterr().out)
    assert called==['P7.1','P7.2','P7.3','P7.4','P7.5']
    assert report['status']=='BLOCKED'


def test_out_is_result_only_not_a_source(tmp_path,capsys):
    stored=tmp_path/'result.json'
    assert wf_gate.main(['--class','druid','--level','60',
                         '--gate','P7.3','--out',str(stored)])==1
    assert json.loads(stored.read_text())['status']=='BLOCKED'
    capsys.readouterr()
    stored.write_text('{"status":"PASS"}')
    assert wf_gate.main(['--class','druid','--level','60',
                         '--gate','P7.3','--out',str(stored)])==1
    assert json.loads(stored.read_text())['status']=='BLOCKED'
