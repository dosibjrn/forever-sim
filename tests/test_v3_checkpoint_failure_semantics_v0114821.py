from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import threading

import pytest

from src.listener import DECISIONS_HTML
from src.service.checkpoints import build_manifest, compatibility_detail
from src.service.http_api import OptimizerHTTPServer
from src.service.models import JobRequest, JobState
from src.service.publication import current_publication, publish_attempt
from src.service.store import QueueStore


def req(**kw):
    base=dict(ruleset='forever', class_name='mage', start_level=20, end_level=20,
              endpoint_mode='mc', source_snapshot='src-a', engine_semantic_hash='sem-a',
              policy_space_version='pol-a', config={'workers':1})
    base.update(kw); return JobRequest(**base)


def mkcp(store, job, attempt, body=b'checkpoint'):
    p=Path(attempt['run_root'])/'state'/'tracks'/'x'/'checkpoints'/'x.pkl'
    p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(body)
    return store.record_checkpoint(build_manifest(job=job,attempt=attempt,path=p).to_dict())


def http(srv, method, path, body=None):
    c=HTTPConnection('127.0.0.1',srv.server_address[1],timeout=3)
    c.request(method,path,body=None if body is None else json.dumps(body),headers={'Content-Type':'application/json'})
    r=c.getresponse(); raw=r.read(); c.close(); return r.status,json.loads(raw or b'{}')


def test_v3_compatibility_matrix_and_integrity_rejection(tmp_path: Path):
    store=QueueStore(tmp_path/'q.sqlite3')
    source,_=store.enqueue(req(),deduplicate=False)
    sj,sa=store.claim_next(owner='s',runs_root=tmp_path/'runs')
    cp=mkcp(store,sj,sa)
    store.finish_attempt(sa['id'],owner='s',outcome='paused')

    exact=compatibility_detail(cp['request'],req().canonical_dict())
    assert exact['compatibility']=='resume'
    drift=compatibility_detail(cp['request'],req(engine_semantic_hash='sem-b',source_snapshot='src-b',policy_space_version='pol-b',config={'workers':2}).canonical_dict())
    assert drift['compatibility']=='seed_only'
    assert {'semantic drift','source drift','policy drift','config drift'} <= set(drift['reasons'])
    hard=compatibility_detail(cp['request'],req(class_name='paladin').canonical_dict())
    assert hard['compatibility']=='incompatible' and 'class drift' in hard['reasons']

    srv=OptimizerHTTPServer(('127.0.0.1',0),store); t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
    try:
        target,_=store.enqueue(req(),deduplicate=False); store.transition(target['id'],JobState.PAUSED)
        # Corrupt hash => explicit rejection.
        Path(cp['path']).write_bytes(b'corrupt')
        status,payload=http(srv,'POST',f"/api/v1/jobs/{target['id']}/saved-state",{'checkpoint_id':cp['id'],'mode':'resume'})
        assert status==400 and 'sha256 mismatch' in payload['error']
        # Missing file => same explicit rejection class.
        Path(cp['path']).unlink()
        status,payload=http(srv,'POST',f"/api/v1/jobs/{target['id']}/saved-state",{'checkpoint_id':cp['id'],'mode':'resume'})
        assert status==400 and 'missing or sha256 mismatch' in payload['error']

        badsrc,_=store.enqueue(req(class_name='paladin'),deduplicate=False)
        bj,ba=store.claim_next(owner='b',runs_root=tmp_path/'runs',max_active_jobs=1,max_resource_units=8)
        badcp=mkcp(store,bj,ba,b'bad'); store.finish_attempt(ba['id'],owner='b',outcome='paused')
        status,payload=http(srv,'POST',f"/api/v1/jobs/{target['id']}/saved-state",{'checkpoint_id':badcp['id'],'mode':'incompatible'})
        assert status==400 and 'incompatible saved state cannot be selected' in payload['error']
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=2)


def _viewer(attempt, marker):
    p=Path(attempt['run_root'])/'state'/'games'/'forever-mage'/'v2'/'viewer.json'
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps({'running':False,'marker':marker,'views':{}}))


def test_v3_failed_and_cancelled_attempts_never_replace_last_good(tmp_path: Path):
    project=tmp_path/'repo'; project.mkdir(); store=QueueStore(project/'state'/'service'/'q.sqlite3')
    good,_=store.enqueue(JobRequest(ruleset='forever',class_name='mage',start_level=20,end_level=20,endpoint_mode='fast'),deduplicate=False)
    gj,ga=store.claim_next(owner='g',runs_root=project/'runs'); _viewer(ga,'good')
    pub=publish_attempt(project,job=gj,attempt=ga); store.record_publication(pub); store.finish_attempt(ga['id'],owner='g',outcome='completed')
    assert current_publication(project)['id']==pub['id']

    failed,_=store.enqueue(JobRequest(ruleset='forever',class_name='mage',start_level=21,end_level=21,endpoint_mode='fast'),deduplicate=False)
    fj,fa=store.claim_next(owner='f',runs_root=project/'runs'); store.finish_attempt(fa['id'],owner='f',outcome='failed',error='boom')
    assert current_publication(project)['id']==pub['id']

    cancelled,_=store.enqueue(JobRequest(ruleset='forever',class_name='mage',start_level=22,end_level=22,endpoint_mode='fast'),deduplicate=False)
    cj,ca=store.claim_next(owner='c',runs_root=project/'runs'); store.finish_attempt(ca['id'],owner='c',outcome='cancelled')
    assert current_publication(project)['id']==pub['id']
    assert store.list_publications(class_name='mage')[0]['id']==pub['id']


def test_v3_ui_explains_compatibility_and_last_good_semantics():
    html=DECISIONS_HTML
    for text in ('Resume from this','Use as seed','cannot load','reasons','A running or failed job does not replace the last good publication.'):
        assert text in html
