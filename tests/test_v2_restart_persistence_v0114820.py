import hashlib
import os
import shutil
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from src import listener
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.models import JobRequest
from src.service.scheduler import Scheduler
from src.service.store import QueueStore


def req(cls='mage', start=20, end=20, mode='mc'):
    return JobRequest(ruleset='forever', class_name=cls, start_level=start, end_level=end, endpoint_mode=mode)


def _checkpoint(store, job, attempt, payload=b'checkpoint'):
    p=Path(attempt['run_root'])/'state'/'games'/'forever-mage'/'v2'/'runtime'/'checkpoint.pkl'
    p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(payload)
    sha=hashlib.sha256(payload).hexdigest()
    return store.record_checkpoint({'job_id':job['id'],'attempt_id':attempt['id'],'path':str(p),'kind':'optimizer_checkpoint','sha256':sha,'size_bytes':len(payload),'request':job['request'],'created_at':time.time()})


def test_queue_order_and_queued_jobs_survive_store_reopen(tmp_path):
    db=tmp_path/'q.sqlite3'; runs=tmp_path/'runs'
    s=QueueStore(db)
    a,_=s.enqueue(req('mage',20,20,'fast'))
    b,_=s.enqueue(req('paladin',20,21,'fast'))
    c,_=s.enqueue(req('druid',20,22,'fast'))
    s.reorder([c['id'],a['id'],b['id']])
    del s
    reopened=QueueStore(db)
    assert [j['id'] for j in reopened.list_jobs(states=['queued'])][:3] == [c['id'],a['id'],b['id']]
    claimed=reopened.claim_next(owner='after-restart',runs_root=runs,lease_seconds=30,max_active_jobs=1,max_resource_units=4)
    assert claimed and claimed[0]['id']==c['id']


def test_expired_lease_recovers_from_compatible_checkpoint_into_new_attempt(tmp_path):
    db=tmp_path/'q.sqlite3'; runs=tmp_path/'runs'
    s=QueueStore(db); job,_=s.enqueue(req())
    first=s.claim_next(owner='dead',runs_root=runs,lease_seconds=1,now=100.0)
    assert first
    cp=_checkpoint(s,first[0],first[1])
    # Simulate daemon death: reopen from only durable DB/artifacts, then recover.
    s2=QueueStore(db)
    second=s2.claim_next(owner='new',runs_root=runs,lease_seconds=10,max_active_jobs=1,max_resource_units=4,now=102.0)
    assert second and second[0]['id']==job['id']
    assert second[1]['id'] != first[1]['id']
    scheduler=Scheduler(s2,runs_root=runs,owner='new')
    staged,seed=scheduler._prepare_saved_state(s2.get(job['id']),second[1])
    assert seed is None and staged is not None
    assert staged['checkpoint_id']==cp['id']
    assert Path(staged['staged_path']).exists()
    assert Path(staged['staged_path']).read_bytes()==b'checkpoint'
    assert s2.get_attempt(first[1]['id'])['state']=='expired'


def test_pending_controls_survive_owner_crash_with_explicit_recovery_semantics(tmp_path):
    db=tmp_path/'q.sqlite3'; runs=tmp_path/'runs'
    # checkpoint remains pending and carries to replacement attempt
    s=QueueStore(db); j,_=s.enqueue(req('mage',20,20,'fast'))
    first=s.claim_next(owner='dead',runs_root=runs,lease_seconds=1,now=10.0); assert first
    s.request_control(j['id'],'checkpoint')
    s2=QueueStore(db)
    repl=s2.claim_next(owner='new',runs_root=runs,lease_seconds=10,max_active_jobs=1,max_resource_units=4,now=12.0)
    assert repl and repl[0]['id']==j['id']
    assert s2.get(j['id'])['control_requested']=='checkpoint'

    # pause/cancel are satisfiable as soon as the dead owner is fenced; no fresh run.
    for action,expected in [('pause','paused'),('cancel','cancelled')]:
        sx=QueueStore(tmp_path/f'{action}.sqlite3'); job,_=sx.enqueue(req('mage',21,21,'fast'))
        claimed=sx.claim_next(owner='dead',runs_root=tmp_path/f'runs-{action}',lease_seconds=1,now=20.0); assert claimed
        sx.request_control(job['id'],action)
        reopened=QueueStore(tmp_path/f'{action}.sqlite3')
        recovered=reopened.recover_expired(now=22.0)
        assert job['id'] in recovered
        state=reopened.get(job['id'])
        assert state['state']==expected and state['control_requested'] is None
        assert reopened.claim_next(owner='new',runs_root=tmp_path/f'runs-{action}',now=22.0) is None


def _chromium():
    return shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')


def _proxy(page, web_port):
    def proxy_route(route):
        req=route.request
        from urllib.parse import urlparse
        parsed=urlparse(req.url)
        target=f'http://127.0.0.1:{web_port}{parsed.path}' + (('?' + parsed.query) if parsed.query else '')
        data=req.post_data.encode('utf-8') if req.post_data is not None else None
        headers={'Content-Type': req.headers.get('content-type','application/json')} if data is not None else {}
        try:
            with urlopen(Request(target,data=data,method=req.method,headers=headers),timeout=3) as resp:
                body=resp.read(); status=resp.status; ctype=resp.headers.get('Content-Type','application/octet-stream')
        except HTTPError as exc:
            body=exc.read(); status=exc.code; ctype=exc.headers.get('Content-Type','application/json')
        route.fulfill(status=status,body=body,headers={'Content-Type':ctype,'Cache-Control':'no-store'})
    page.route('http://listener.test/**',proxy_route)


def _load_listener_page(page, web_port):
    with urlopen(f'http://127.0.0.1:{web_port}/decisions',timeout=3) as resp:
        html=resp.read().decode('utf-8')
    html=html.replace('<head>','<head><base href="http://listener.test/"><script>Object.defineProperty(window,\'localStorage\',{value:{getItem(){return null},setItem(){},removeItem(){},clear(){}}});</script>',1)
    page.set_content(html,wait_until='domcontentloaded',timeout=10000)
    page.wait_for_selector('#jobList .job-row',timeout=5000)


def test_browser_listener_and_service_restart_reconstruct_live_state(tmp_path, monkeypatch):
    chrome=_chromium()
    if not chrome:
        if os.environ.get('REQUIRE_CHROMIUM')=='1': pytest.fail('Chromium is required by V2')
        pytest.skip('Chromium not installed')
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        if os.environ.get('REQUIRE_CHROMIUM')=='1': pytest.fail('Playwright is required by V2')
        pytest.skip('Playwright not installed')

    db=tmp_path/'service.sqlite3'; runs=tmp_path/'runs'
    store=QueueStore(db)
    queued,_=store.enqueue(req('paladin',20,21,'fast'))
    running,_=store.enqueue(req('mage',20,20,'fast'))
    claimed=store.claim_next(owner='live-worker',runs_root=runs,lease_seconds=120,max_active_jobs=1,max_resource_units=4); assert claimed
    assert claimed[0]['id']==queued['id'] or claimed[0]['id']==running['id']
    live_id=claimed[0]['id']
    store.record_event(live_id,'runtime_progress',{'phase':'optimize','stage':'v2-restart','progress':{'mode':'determinate','current':2,'total':5,'fraction':0.4,'unit':'steps'},'best_so_far':{'best_validated_hours':8.25}})

    api=OptimizerHTTPServer(('127.0.0.1',0),store); api_t=threading.Thread(target=api.serve_forever,daemon=True); api_t.start()
    monkeypatch.setattr(listener,'_SERVICE_CLIENT',ServiceClient(f'http://127.0.0.1:{api.server_address[1]}',timeout=1.0))
    remote='<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>'
    monkeypatch.setattr(listener,'DECISIONS_HTML',listener.DECISIONS_HTML.replace(remote,''))
    web=listener.ThreadingHTTPServer(('127.0.0.1',0),listener.Handler); web_t=threading.Thread(target=web.serve_forever,daemon=True); web_t.start()

    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=chrome,headless=True,args=['--no-sandbox','--disable-gpu','--disable-dev-shm-usage'])
            page=browser.new_page(viewport={'width':1400,'height':1000}); _proxy(page,web.server_address[1]); _load_listener_page(page,web.server_address[1])
            txt=page.locator('#jobList').inner_text().lower(); assert 'running' in txt and 'queued' in txt
            browser.close()  # browser close while run remains durable

            # Restart service HTTP and listener HTTP processes, preserving only DB/artifacts.
            web.shutdown(); web.server_close(); web_t.join(timeout=2)
            api.shutdown(); api.server_close(); api_t.join(timeout=2)
            reopened=QueueStore(db)
            api2=OptimizerHTTPServer(('127.0.0.1',0),reopened); api2_t=threading.Thread(target=api2.serve_forever,daemon=True); api2_t.start()
            monkeypatch.setattr(listener,'_SERVICE_CLIENT',ServiceClient(f'http://127.0.0.1:{api2.server_address[1]}',timeout=1.0))
            web2=listener.ThreadingHTTPServer(('127.0.0.1',0),listener.Handler); web2_t=threading.Thread(target=web2.serve_forever,daemon=True); web2_t.start()
            try:
                browser2=pw.chromium.launch(executable_path=chrome,headless=True,args=['--no-sandbox','--disable-gpu','--disable-dev-shm-usage'])
                page2=browser2.new_page(viewport={'width':1400,'height':1000}); _proxy(page2,web2.server_address[1]); _load_listener_page(page2,web2.server_address[1])
                txt2=page2.locator('#jobList').inner_text().lower(); assert 'running' in txt2 and 'queued' in txt2
                assert 'v2-restart' in txt2 or 'optimize' in txt2
                assert reopened.get(live_id)['state']=='running'
                browser2.close()
            finally:
                web2.shutdown(); web2.server_close(); web2_t.join(timeout=2)
                api2.shutdown(); api2.server_close(); api2_t.join(timeout=2)
    finally:
        try:
            web.shutdown(); web.server_close()
        except Exception: pass
        try:
            api.shutdown(); api.server_close()
        except Exception: pass
