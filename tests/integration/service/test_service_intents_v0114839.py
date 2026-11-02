from __future__ import annotations

from http.client import HTTPConnection
from pathlib import Path
import json
import threading

from src.service.http_api import OptimizerHTTPServer
from src.service.intents import compile_intent, public_intent_from_job
from src.service.executors import V2RunnerExecutor
from src.service.store import QueueStore


def _server(tmp_path: Path):
    store=QueueStore(tmp_path/'q.sqlite3')
    srv=OptimizerHTTPServer(('127.0.0.1',0),store)
    t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
    return srv,t,store


def _post(srv,path,body):
    conn=HTTPConnection('127.0.0.1',srv.server_address[1],timeout=3)
    conn.request('POST',path,body=json.dumps(body),headers={'Content-Type':'application/json'})
    res=conn.getresponse(); data=json.loads(res.read() or b'{}'); status=res.status; conn.close()
    return status,data


def test_recompute_range_compiles_domain_intent_to_internal_runner_job():
    x=compile_intent({'action':'recompute_range','class_name':'druid','from_level':10,'to_level':60})
    assert x.request.class_name=='druid'
    assert (x.request.start_level,x.request.end_level)==(10,60)
    assert x.request.endpoint_mode=='smooth'
    assert x.request.config['service_intent']=={'action':'recompute_range','depth':'standard'}
    plan=V2RunnerExecutor().plan({'request':x.request.canonical_dict()})
    assert '--beam-width' in plan.command and '10' in plan.command
    assert '--family-keep' in plan.command and '--final-k' in plan.command


def test_deepen_level_is_single_level_and_widens_search_without_exposing_backend_choice():
    x=compile_intent({'action':'deepen_level','class_name':'druid','level':34,'depth':'wide'})
    assert x.request.start_level==x.request.end_level==34
    assert x.request.objective=='endpoint'
    assert x.request.config['beam_width']==72
    assert x.request.config['final_k']==40
    assert public_intent_from_job({'request':x.request.canonical_dict()})=={
        'action':'deepen_level','class_name':'druid','depth':'wide','level':34,
    }


def test_investigate_defaults_to_deep_and_preserves_reason():
    x=compile_intent({'action':'investigate_level','class_name':'mage','level':34,'reason':'result looks suspicious'})
    meta=x.request.config['service_intent']
    assert meta['depth']=='deep' and meta['reason']=='result looks suspicious'
    assert x.request.config['beam_width']==128 and x.request.config['final_k']==64


def test_http_intent_endpoint_enqueues_and_records_user_intent(tmp_path: Path):
    srv,t,store=_server(tmp_path)
    try:
        status,payload=_post(srv,'/api/v1/intents',{
            'action':'deepen_level','class_name':'paladin','level':34,'depth':'wide','priority':4,
        })
        assert status==201
        job=payload['job']
        assert job['priority']==4
        assert payload['intent']['action']=='deepen_level'
        assert payload['intent']['level']==34
        assert 'smooth' not in payload['summary'].lower()
        events=store.events(job['id'])
        assert events[-1]['kind']=='intent_submitted'
        assert events[-1]['payload']['intent']['depth']=='wide'
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=2)


def test_intent_validation_rejects_bad_ranges_and_unknown_actions():
    for body in (
        {'action':'recompute_range','class_name':'druid','from_level':40,'to_level':20},
        {'action':'run_mc','class_name':'mage','level':34},
    ):
        try:
            compile_intent(body)
        except ValueError:
            pass
        else:
            raise AssertionError(body)
