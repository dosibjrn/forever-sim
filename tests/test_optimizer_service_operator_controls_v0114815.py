from http.client import HTTPConnection
import json
import threading
from pathlib import Path

from src.service.http_api import OptimizerHTTPServer
from src.service.models import JobRequest
from src.service.store import QueueStore
from src.listener import DECISIONS_HTML


def _server(tmp_path: Path):
    store=QueueStore(tmp_path/'q.sqlite3')
    srv=OptimizerHTTPServer(('127.0.0.1',0),store)
    t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
    return srv,t,store


def _req(srv, method, path, body=None):
    conn=HTTPConnection('127.0.0.1',srv.server_address[1],timeout=3)
    raw=None if body is None else json.dumps(body)
    conn.request(method,path,body=raw,headers={'Content-Type':'application/json'})
    res=conn.getresponse(); data=res.read(); status=res.status; conn.close()
    return status,json.loads(data or b'{}')


def test_clone_reorder_and_checkpoint_control_contract(tmp_path: Path):
    srv,t,store=_server(tmp_path)
    try:
        base={"ruleset":"forever","class_name":"mage","start_level":11,"end_level":20,"endpoint_mode":"fast"}
        _,a=_req(srv,'POST','/api/v1/jobs',base)
        _,b=_req(srv,'POST','/api/v1/jobs',{**base,"end_level":30,"deduplicate":False})
        aid,bid=a['job']['id'],b['job']['id']

        status,out=_req(srv,'POST',f'/api/v1/jobs/{aid}/clone',{"overrides":{"end_level":40},"priority":7,"deduplicate":False})
        assert status==201 and out['job']['request']['end_level']==40 and out['job']['priority']==7
        assert out['job']['request']['class_name']=='mage' and out['source_job_id']==aid

        status,out=_req(srv,'POST','/api/v1/queue/reorder',{"job_ids":[bid,aid]})
        assert status==200
        same_priority=[j for j in out['jobs'] if j['id'] in {aid,bid}]
        assert [j['id'] for j in same_priority]==[bid,aid]

        claimed=store.claim_next(owner='u3',runs_root=tmp_path/'runs',max_active_jobs=1,max_resource_units=8)
        assert claimed is not None
        running,_=claimed
        status,out=_req(srv,'POST',f"/api/v1/jobs/{running['id']}/checkpoint",{})
        assert status==202 and out['control_requested']=='checkpoint'
        status,rejected=_req(srv,'POST',f"/api/v1/jobs/{running['id']}/cancel",{})
        assert status==409 and 'checkpoint already pending' in rejected['error']
        ack=store.acknowledge_control(running['id'],'checkpoint',payload={'checkpoint_ids':['cp1']})
        assert ack['control_requested'] is None
        assert store.events(running['id'])[-1]['kind']=='control_accepted'
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=2)


def test_listener_operator_controls_are_thin_and_truthful():
    html=DECISIONS_HTML
    for text in ('checkpoint now','rerun/edit','reorder_up','reorder_down','Pending:','Accepted:','Rejected:','/api/service/queue/reorder'):
        assert text in html
    assert 'QueueStore(' not in html
    assert 'subprocess.run' not in html
