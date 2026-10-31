from http.client import HTTPConnection
import json
from pathlib import Path
import threading

from src.listener import DECISIONS_HTML
from src.service.checkpoints import build_manifest, compatibility_detail
from src.service.http_api import OptimizerHTTPServer
from src.service.models import JobRequest, JobState
from src.service.scheduler import Scheduler
from src.service.store import QueueStore


def req(**kw):
    base=dict(ruleset='forever',class_name='mage',start_level=11,end_level=60,
              endpoint_mode='mc',source_snapshot='src-a',engine_semantic_hash='sem-a',
              policy_space_version='pol-a',config={'school':'frost','workers':1})
    base.update(kw); return JobRequest(**base)


def checkpoint(store,job,attempt,body=b'checkpoint'):
    p=Path(attempt['run_root'])/'state'/'tracks'/'buy_water'/'checkpoints'/'x.pkl'
    p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(body)
    return store.record_checkpoint(build_manifest(job=job,attempt=attempt,path=p).to_dict())


def server(tmp_path):
    store=QueueStore(tmp_path/'q.sqlite3'); srv=OptimizerHTTPServer(('127.0.0.1',0),store)
    t=threading.Thread(target=srv.serve_forever,daemon=True); t.start(); return srv,t,store


def http(srv,method,path,body=None):
    c=HTTPConnection('127.0.0.1',srv.server_address[1],timeout=3)
    c.request(method,path,body=None if body is None else json.dumps(body),headers={'Content-Type':'application/json'})
    r=c.getresponse(); raw=r.read(); status=r.status; c.close(); return status,json.loads(raw or b'{}')


def test_compatibility_reasons_are_explicit():
    a=req().canonical_dict()
    assert compatibility_detail(a,a)['compatibility']=='resume'
    seed=req(engine_semantic_hash='sem-b',source_snapshot='src-b',policy_space_version='pol-b',config={'school':'arcane'}).canonical_dict()
    d=compatibility_detail(a,seed)
    assert d['compatibility']=='seed_only'
    assert {'semantic drift','source drift','policy drift','config drift'} <= set(d['reasons'])
    bad=req(class_name='paladin').canonical_dict()
    d=compatibility_detail(a,bad)
    assert d['compatibility']=='incompatible' and 'class drift' in d['reasons']


def test_saved_state_endpoint_lists_and_enforces_modes(tmp_path: Path):
    srv,t,store=server(tmp_path)
    try:
        source,_=store.enqueue(req(),deduplicate=False)
        sa=store.claim_next(owner='s',runs_root=tmp_path/'runs')[1]
        cp_resume=checkpoint(store,source,sa)
        store.finish_attempt(sa['id'],owner='s',outcome='paused')

        target,_=store.enqueue(req(),deduplicate=False)
        store.transition(target['id'],JobState.PAUSED)
        status,payload=http(srv,'GET',f"/api/v1/jobs/{target['id']}/saved-states")
        row=next(x for x in payload['saved_states'] if x['id']==cp_resume['id'])
        assert status==200 and row['compatibility']=='resume' and row['actions']['resume'] is True
        status,payload=http(srv,'POST',f"/api/v1/jobs/{target['id']}/saved-state",{'checkpoint_id':cp_resume['id'],'mode':'resume'})
        assert status==200 and payload['job']['state']=='queued'
        assert payload['job']['selected_checkpoint_id']==cp_resume['id']

        store.transition(target['id'],JobState.PAUSED)
        drift,_=store.enqueue(req(engine_semantic_hash='sem-old'),deduplicate=False)
        da=store.claim_next(owner='d',runs_root=tmp_path/'runs',max_active_jobs=1,max_resource_units=8)[1]
        assert da['job_id']==drift['id']
        cp_seed=checkpoint(store,drift,da,body=b'seed')
        store.finish_attempt(da['id'],owner='d',outcome='paused')
        status,payload=http(srv,'GET',f"/api/v1/jobs/{target['id']}/saved-states")
        row=next(x for x in payload['saved_states'] if x['id']==cp_seed['id'])
        assert row['compatibility']=='seed_only' and row['actions']['seed_only'] is True
        status,payload=http(srv,'POST',f"/api/v1/jobs/{target['id']}/saved-state",{'checkpoint_id':cp_seed['id'],'mode':'resume'})
        assert status==400 and 'seed_only, not resume' in payload['error']
        status,payload=http(srv,'POST',f"/api/v1/jobs/{target['id']}/saved-state",{'checkpoint_id':cp_seed['id'],'mode':'seed_only'})
        assert status==200 and payload['job']['selected_checkpoint_mode']=='seed_only'
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=2)


def test_seed_only_uses_read_only_import_not_numeric_resume(tmp_path: Path):
    store=QueueStore(tmp_path/'q.sqlite3')
    old,_=store.enqueue(req(engine_semantic_hash='old'),deduplicate=False)
    oa=store.claim_next(owner='old',runs_root=tmp_path/'runs')[1]
    cp=checkpoint(store,old,oa,body=b'seed')
    store.finish_attempt(oa['id'],owner='old',outcome='paused')

    target,_=store.enqueue(req(),deduplicate=False)
    store.select_saved_state(target['id'],cp['id'],'seed_only')
    sched=Scheduler(store,runs_root=tmp_path/'runs',owner='new')
    claimed=sched.claim(); assert claimed is not None
    resume,seed=sched._prepare_saved_state(claimed.job,claimed.attempt)
    assert resume is None and seed['checkpoint_id']==cp['id']
    assert seed['source_run_root']==oa['run_root']
    assert not list(Path(claimed.attempt['run_root']).rglob('*.pkl'))
    cmd=list(__import__('src.service.executors',fromlist=['executor_for']).executor_for(claimed.job).plan(claimed.job).command)
    cmd += ['--import-state-dir',seed['source_run_root']]
    assert '--import-state-dir' in cmd


def test_listener_exposes_saved_state_actions_without_direct_store():
    html=DECISIONS_HTML
    for text in ('saved states','Resume from this','Use as seed','seed_only','incompatible','saved-state'):
        assert text in html
    assert 'QueueStore(' not in html
