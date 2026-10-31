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
from src.service.store import QueueStore


def _chromium():
    return shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')


def _wait_until(fn, timeout=4.0, step=0.03):
    end=time.time()+timeout
    last=None
    while time.time()<end:
        try:
            value=fn()
            if value:
                return value
        except Exception as exc:
            last=exc
        time.sleep(step)
    if last:
        raise last
    raise AssertionError('condition not met before timeout')


def test_v1_real_rendered_operator_workflow(tmp_path, monkeypatch):
    chrome=_chromium()
    if not chrome:
        if os.environ.get('REQUIRE_CHROMIUM') == '1':
            pytest.fail('Chromium is required by V1')
        pytest.skip('Chromium not installed')
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        if os.environ.get('REQUIRE_CHROMIUM') == '1':
            pytest.fail('Playwright is required by V1')
        pytest.skip('Playwright not installed')

    db=tmp_path/'service.sqlite3'
    runs=tmp_path/'runs'
    store=QueueStore(db)
    api=OptimizerHTTPServer(('127.0.0.1',0),store)
    api_thread=threading.Thread(target=api.serve_forever,daemon=True); api_thread.start()
    service_url=f'http://127.0.0.1:{api.server_address[1]}'
    monkeypatch.setattr(listener,'_SERVICE_CLIENT',ServiceClient(service_url,timeout=1.0))

    # Real listener handler + real decision snapshot; suppress remote tooltip JS so
    # validation has no internet dependency.
    remote='<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>'
    monkeypatch.setattr(listener,'DECISIONS_HTML',listener.DECISIONS_HTML.replace(remote,''))
    web=listener.ThreadingHTTPServer(('127.0.0.1',0),listener.Handler)
    web_thread=threading.Thread(target=web.serve_forever,daemon=True); web_thread.start()
    url=f'http://127.0.0.1:{web.server_address[1]}/decisions'

    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=chrome,headless=True,args=['--no-sandbox','--disable-gpu','--disable-dev-shm-usage'])
            page=browser.new_page(viewport={'width':1440,'height':1200})
            compute_requests=[]
            page.on('request',lambda req: compute_requests.append(req.url) if ('/api/decisions/validate' in req.url or '/api/decisions/constraint' in req.url) else None)

            # This execution environment blocks Chromium's direct loopback navigation.
            # Keep the browser/UI real and proxy browser requests through Python to the
            # real listener socket; the listener itself still proxies service calls.
            def proxy_route(route):
                req=route.request
                from urllib.parse import urlparse
                parsed=urlparse(req.url)
                target=url + ('?' + parsed.query if parsed.query else '') if parsed.path=='/decisions' else f'http://127.0.0.1:{web.server_address[1]}{parsed.path}' + (('?' + parsed.query) if parsed.query else '')
                data=req.post_data.encode('utf-8') if req.post_data is not None else None
                headers={'Content-Type': req.headers.get('content-type','application/json')} if data is not None else {}
                try:
                    with urlopen(Request(target,data=data,method=req.method,headers=headers),timeout=3) as resp:
                        body=resp.read(); status=resp.status; ctype=resp.headers.get('Content-Type','application/octet-stream')
                except HTTPError as exc:
                    body=exc.read(); status=exc.code; ctype=exc.headers.get('Content-Type','application/json')
                route.fulfill(status=status,body=body,headers={'Content-Type':ctype,'Cache-Control':'no-store'})
            page.route('http://listener.test/**',proxy_route)
            with urlopen(url,timeout=3) as resp:
                html=resp.read().decode('utf-8')
            html=html.replace('<head>','<head><base href="http://listener.test/"><script>Object.defineProperty(window,\'localStorage\',{value:{getItem(){return null},setItem(){},removeItem(){},clear(){}}});</script>',1)
            page.set_content(html,wait_until='domcontentloaded',timeout=10000)
            page.wait_for_selector('#enqueueJob',timeout=5000)
            page.select_option('#classPick','paladin')

            # 1-2: enqueue two distinct jobs from the rendered UI.
            page.select_option('#jobAction','recompute_range'); page.select_option('#jobDepth','standard'); page.fill('#jobStart','20'); page.fill('#jobEnd','20')
            page.click('#enqueueJob'); _wait_until(lambda: len(store.list_jobs())==1)
            page.wait_for_function("document.querySelector('#serviceMessage').innerText.startsWith('Accepted:')")
            # Set the second override and click in one browser task, then wait for
            # the actual POST response. The route-proxied rendered workflow can take a
            # few seconds under concurrent status polling; waiting on the network
            # acknowledgement avoids timing the durable-store assertion against an
            # in-flight request.
            with page.expect_response(lambda r: r.url.endswith('/api/service/intents') and r.request.method == 'POST', timeout=10000) as pending_enqueue:
                page.evaluate("""() => {
                    const end=document.querySelector('#jobEnd');
                    end.value='21';
                    end.dispatchEvent(new Event('input',{bubbles:true}));
                    document.querySelector('#enqueueJob').click();
                }""")
            assert pending_enqueue.value.ok
            _wait_until(lambda: len(store.list_jobs())==2, timeout=3.0)
            jobs=_wait_until(lambda: store.list_jobs() if len(store.list_jobs())==2 else None)
            queued=[j for j in jobs if j['state']=='queued']
            assert len(queued)==2
            first,second=queued[0],queued[1]

            # 3-4: rendered queue observes queued state and reorders through UI.
            page.click('#refreshJobs')
            page.wait_for_selector(f'button[data-job-action="reorder_up"][data-job-id="{second["id"]}"]')
            page.click(f'button[data-job-action="reorder_up"][data-job-id="{second["id"]}"]'); page.wait_for_timeout(300)
            _wait_until(lambda: store.list_jobs(states=['queued'])[0]['id']==second['id'])

            claimed=store.claim_next(owner='v1-worker',runs_root=runs,lease_seconds=60,max_active_jobs=1,max_resource_units=4)
            assert claimed is not None
            running,attempt=claimed
            assert running['id']==second['id']
            store.record_event(running['id'],'runtime_progress',{'phase':'optimize','stage':'validation-workflow','current':1,'total':4,'unit':'step','best_so_far':{'best_validated_hours':9.5}})
            page.click('#refreshJobs')
            page.wait_for_selector(f'.job-row button[data-job-action="checkpoint"][data-job-id="{running["id"]}"]')
            assert 'running' in page.locator('#jobList').inner_text()

            # 5: request checkpoint from UI; validation worker reaches a safe boundary,
            # records durable artifact, then pause is requested and acknowledged.
            page.click(f'button[data-job-action="checkpoint"][data-job-id="{running["id"]}"]'); page.wait_for_timeout(300)
            _wait_until(lambda: store.get(running['id'])['control_requested']=='checkpoint')
            cp_path=Path(attempt['run_root'])/'runtime'/'controller.json'; cp_path.parent.mkdir(parents=True,exist_ok=True); cp_path.write_text('{"v1":true}',encoding='utf-8')
            sha=hashlib.sha256(cp_path.read_bytes()).hexdigest()
            cp=store.record_checkpoint({'job_id':running['id'],'attempt_id':attempt['id'],'path':str(cp_path),'kind':'controller','sha256':sha,'size_bytes':cp_path.stat().st_size,'request':running['request'],'created_at':time.time()})
            store.acknowledge_control(running['id'],'checkpoint',payload={'checkpoint_ids':[cp['id']]})
            page.click('#refreshJobs')
            _wait_until(lambda: 'checkpoint' in page.locator('#jobList').inner_text().lower())
            page.click(f'button[data-job-action="pause"][data-job-id="{running["id"]}"]'); page.wait_for_timeout(300)
            _wait_until(lambda: store.get(running['id'])['control_requested']=='pause')
            store.acknowledge_control(running['id'],'pause')
            store.finish_attempt(attempt['id'],owner='v1-worker',outcome='paused')

            # Preserve a last-good publication while the same job is paused/requeued.
            pub_root=tmp_path/'published'/'paladin-v1'; pub_root.mkdir(parents=True)
            store.record_publication({'id':'v1-pub','job_id':running['id'],'attempt_id':attempt['id'],'state_root':str(pub_root),'parent_id':None,'request':running['request'],'created_at':time.time()})
            page.click('#refreshJobs')
            page.wait_for_selector(f'button[data-job-action="saved_states"][data-job-id="{running["id"]}"]')

            # 6: explicit U4 resume from saved-state UI, never implicit fresh rerun.
            page.click(f'button[data-job-action="saved_states"][data-job-id="{running["id"]}"]')
            page.wait_for_selector(f'button[data-saved-mode="resume"][data-checkpoint-id="{cp["id"]}"]')
            page.click(f'button[data-saved-mode="resume"][data-checkpoint-id="{cp["id"]}"]'); page.wait_for_timeout(300)
            _wait_until(lambda: store.get(running['id'])['state']=='queued')
            assert store.get(running['id'])['selected_checkpoint_id']==cp['id']

            # 7: rerun/edit from rendered UI with one explicit override.
            page.click('#refreshJobs')
            page.click(f'button[data-job-action="clone"][data-job-id="{running["id"]}"]')
            page.wait_for_function("document.querySelector('#clearClone').style.display !== 'none'")
            page.fill('#jobEnd','22')
            page.click('#enqueueJob'); page.wait_for_timeout(300)
            clone=_wait_until(lambda: next((j for j in store.list_jobs() if j['id'] not in {first['id'],running['id']}),None))
            assert clone['request']['end_level']==22

            # 8: cancel one queued job from UI.
            page.click('#refreshJobs')
            page.click(f'button[data-job-action="cancel"][data-job-id="{first["id"]}"]'); page.wait_for_timeout(300)
            _wait_until(lambda: store.get(first['id'])['state']=='cancelled')

            # 9: latest-good publication and lineage remain visible independently of live state.
            page.click('#refreshJobs')
            _wait_until(lambda: 'v1-pub' in page.locator('#publicationList').inner_text())
            page.click(f'button[data-job-action="history"][data-job-id="{running["id"]}"]')
            page.wait_for_function("document.querySelector('#lineagePanel').innerText.includes('1 publication(s)')")
            assert '1 checkpoint(s)' in page.locator('#lineagePanel').inner_text()

            # 10: reload reconstructs from service, not browser cache.
            # Re-create the document from the real listener to prove durable state
            # reconstruction rather than relying on browser DOM/cache.
            with urlopen(url,timeout=3) as resp:
                html2=resp.read().decode('utf-8')
            html2=html2.replace('<head>','<head><base href="http://listener.test/"><script>Object.defineProperty(window,\'localStorage\',{value:{getItem(){return null},setItem(){},removeItem(){},clear(){}}});</script>',1)
            page.set_content(html2,wait_until='domcontentloaded',timeout=10000)
            page.wait_for_selector('#jobList .job-row',timeout=5000)
            _wait_until(lambda: 'v1-pub' in page.locator('#publicationList').inner_text())
            text=page.locator('#jobList').inner_text().lower()
            assert 'cancelled' in text and 'queued' in text
            assert compute_requests==[], 'operator workflow must not start browser-side decision compute'
            browser.close()
    finally:
        web.shutdown(); web.server_close(); web_thread.join(timeout=2)
        api.shutdown(); api.server_close(); api_thread.join(timeout=2)
