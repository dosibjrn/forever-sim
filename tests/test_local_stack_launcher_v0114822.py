import json
from pathlib import Path

import src.listener as listener
import src.service.local_stack as local_stack


def test_launcher_scripts_use_local_stack_supervisor():
    root=Path(__file__).resolve().parents[1]
    assert 'src.service.local_stack' in (root/'service-start.sh').read_text()
    assert '--stop' in (root/'service-stop.sh').read_text()


def test_listener_local_runtime_contract(tmp_path, monkeypatch):
    state=tmp_path/'state.json'; command=tmp_path/'command.json'; token='secret-token'
    state.write_text(json.dumps({'token':token,'listener_url':'http://127.0.0.1:8766/decisions','service_url':'http://127.0.0.1:8765','children':{'api':{'running':True,'pid':1},'daemon':{'running':True,'pid':2},'listener':{'running':True,'pid':3}}}))
    monkeypatch.setattr(listener,'_LOCAL_STACK_STATE',state)
    monkeypatch.setattr(listener,'_LOCAL_STACK_COMMAND',command)
    monkeypatch.setattr(listener,'_LOCAL_STACK_TOKEN',token)
    snap=listener.local_runtime_snapshot()
    assert snap['available'] and snap['children']['daemon']['running']
    assert listener.request_local_runtime('stop-daemon',token)['accepted']
    obj=json.loads(command.read_text())
    assert obj['command']=='stop-daemon' and obj['token']==token


def test_service_stop_writes_authenticated_command(tmp_path, monkeypatch):
    state=tmp_path/'state.json'; command=tmp_path/'command.json'
    state.write_text(json.dumps({'token':'abc'}))
    monkeypatch.setattr(local_stack,'STATE_FILE',state)
    monkeypatch.setattr(local_stack,'COMMAND_FILE',command)
    assert local_stack.request_stop('stop-all') == 0
    assert json.loads(command.read_text())['command']=='stop-all'
