"""G50i: listener-native source Decision queue submit, status, explicit inspect."""
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from src.service.store import QueueStore
from src.service.scheduler import Scheduler
from src.service.http_api import OptimizerHTTPServer
from src.service.client import ServiceClient
from src.game.data.forever.queue_capabilities import PINNED_FOREVER_AS_OF
from src.version import SOFTWARE_VERSION


def request_json(url, body=None):
    payload=None if body is None else json.dumps(body).encode('utf-8')
    req=Request(url, data=payload, headers={'Content-Type':'application/json'} if payload else {},
                method='POST' if payload else 'GET')
    try:
        with urlopen(req,timeout=12) as response:
            return response.status,json.load(response)
    except HTTPError as e:
        raw=e.read().decode()
        try: result=json.loads(raw)
        except ValueError: result={"error":raw}
        return e.code,result


def native_request(cls='mage', level=10):
    return {'ruleset':'forever','class_name':cls,'start_level':level,'end_level':level,
            'objective':'endpoint','endpoint_mode':'generic_decision',
            'forever_build_as_of':PINNED_FOREVER_AS_OF,'source_snapshot':'current',
            'engine_semantic_hash':'current','policy_space_version':'current',
            'config':{},'validation_modes':[],'priority':0,'deduplicate':False}


def test_real_listener_service_submit_status_worker_and_explicit_inspect(tmp_path,monkeypatch):
    import src.listener as listener
    from http.server import ThreadingHTTPServer
    monkeypatch.setenv('PYTHONPATH',str(Path(__file__).resolve().parents[1]))
    store=QueueStore(tmp_path/'q.sqlite3')
    service=OptimizerHTTPServer(('127.0.0.1',0),store,project_root=tmp_path)
    st=Thread(target=service.serve_forever,daemon=True);st.start()
    monkeypatch.setattr(listener,'_SERVICE_CLIENT',ServiceClient(f'http://127.0.0.1:{service.server_address[1]}',timeout=5))
    ui=ThreadingHTTPServer(('127.0.0.1',0),listener.Handler)
    ut=Thread(target=ui.serve_forever,daemon=True);ut.start()
    root=f'http://127.0.0.1:{ui.server_address[1]}'
    try:
        status,response=request_json(root+'/api/service/jobs',native_request('mage',10))
        assert status==200 and response['created'] is True,response
        job=response['job'];id=job['id']
        assert job['state']=='queued' and job['request']['config']['producer_version']==SOFTWARE_VERSION
        status,read=request_json(root+'/api/service/jobs/'+id)
        assert status==200 and read['id']==id and read['state']=='queued'
        status,read=request_json(root+'/api/decisions/queued?backend=generic&class=mage&level=10')
        assert status==503 and read['legacy_fallback'] is False
        result=Scheduler(store,runs_root=tmp_path/'runs').run_once(project_root=tmp_path)
        assert result['state']=='completed',result
        status,read=request_json(root+'/api/service/jobs/'+id)
        assert status==200 and read['state']=='completed'
        status,pub=request_json(root+'/api/decisions/queued?backend=generic&class=mage&level=10')
        assert status==200 and pub['job_id']==id
        assert pub['decision']['identity']['class_name']=='mage'
        assert pub['decision']['identity']['level']==10
        assert pub['decision']['provenance']['legacy_fallback'] is False
        assert pub['producer_version']==SOFTWARE_VERSION
        status,_=request_json(root+'/api/service/jobs/'+id+'/extra')
        assert status!=200
        status,_=request_json(root+'/api/service/jobs/not-a-uuid')
        assert status==400
        status,rejected=request_json(root+'/api/service/jobs',native_request('mage',11))
        assert status==503 or status==400,rejected  # service admission must reject unsupported scope
        assert len(store.list_jobs())==1
    finally:
        ui.shutdown();ui.server_close();ut.join(timeout=5)
        service.shutdown();service.server_close();st.join(timeout=5)


def test_browser_queue_lifecycle_and_fail_closed_inspection():
    from playwright.sync_api import sync_playwright
    from src.listener import DECISIONS_HTML
    html=DECISIONS_HTML.replace('<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>','')
    html=html.replace("load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);",'// G50i controlled browser harness')
    html=html.replace('localStorage.','window.__g50iStorage.')
    html=html.replace('<head>','<head><script>window.__g50iStorage={getItem:()=>null,setItem:()=>{}};</script>',1)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,
                                   args=['--no-sandbox','--disable-dev-shm-usage','--disable-background-networking'])
        try:
            page=browser.new_page()
            page.set_content(html,wait_until='domcontentloaded')
            page.evaluate('''() => {
              data={active_backend:'generic',decisions:[],class_metadata:{mage:{queued_native_decision_levels:[10]},druid:{queued_native_decision_levels:[10,11]}}};
              state.cls='mage';state.level=10;state.backend='generic';
              window.__g50i={status:'queued',error:false,publicationJob:'a'.repeat(32),post:null,posts:0};
              window.fetch=async (url,options={})=>{
                if(url==='/api/service/jobs'){
                  window.__g50i.posts++;window.__g50i.post=JSON.parse(options.body);
                  return {ok:true,status:200,json:async()=>({created:true,job:{id:'a'.repeat(32),state:'queued',request:{...window.__g50i.post,config:{producer_version:CURRENT_SOFTWARE_VERSION}}}})};
                }
                if(url.startsWith('/api/service/jobs/')){
                  if(window.__g50i.error)throw Error('service unavailable');
                  return {ok:true,status:200,json:async()=>({id:'a'.repeat(32),state:window.__g50i.status,
                    request:{...window.__g50i.post,config:{producer_version:CURRENT_SOFTWARE_VERSION}}})};
                }
                if(url.startsWith('/api/decisions/queued?'))return {ok:true,status:200,json:async()=>({
                  authority:'queued_native_generic_decision',legacy_fallback:false,
                  execution_authority:'native_generic_decision',publication_id:'test-publication',job_id:window.__g50i.publicationJob,
                  decision:{identity:{class_name:'mage',level:10},backend:{id:'generic',version:CURRENT_SOFTWARE_VERSION},
                  provenance:{legacy_fallback:false},objective:{status:'runtime_probe'}}})};
                throw Error('unexpected '+url);
              };
              document.querySelector('#enqueueQueuedNative').addEventListener('click',enqueueNativeQueueDecision);
              document.querySelector('#loadQueuedNative').addEventListener('click',loadQueuedNativeDecision);
              document.querySelector('#retryQueuedNative').addEventListener('click',()=>{nativeQueueJob.failures=0;nativeQueueJob.state='checking';void pollNativeQueueStatus(true)});
              renderQueuedNativeView();
            }''')
            assert not page.locator('#enqueueQueuedNative').is_disabled()
            page.click('#enqueueQueuedNative')
            page.wait_for_function("document.querySelector('#queuedNativeStatus').textContent.includes('queued')")
            assert page.locator('#loadQueuedNative').is_disabled()
            assert page.evaluate('window.__g50i.post.endpoint_mode')=='generic_decision'
            assert page.evaluate('window.__g50i.post.forever_build_as_of')==PINNED_FOREVER_AS_OF
            assert page.evaluate('window.__g50i.post.deduplicate') is False
            page.evaluate("window.__g50i.status='running'")
            page.evaluate('pollNativeQueueStatus()')
            page.wait_for_function("document.querySelector('#queuedNativeStatus').textContent.includes('running')")
            assert page.locator('#loadQueuedNative').is_disabled()
            page.evaluate("window.__g50i.status='completed'")
            page.evaluate('pollNativeQueueStatus()')
            page.wait_for_function("document.querySelector('#queuedNativeStatus').textContent.includes('completed')")
            assert not page.locator('#loadQueuedNative').is_disabled()
            page.evaluate("window.__g50i.publicationJob='b'.repeat(32)")
            page.click('#loadQueuedNative')
            page.wait_for_function("document.querySelector('#queuedNativeResult').textContent.includes('another job')")
            assert 'test-publication' not in page.locator('#queuedNativeResult').inner_text()
            page.evaluate("window.__g50i.publicationJob='a'.repeat(32)")
            page.click('#loadQueuedNative')
            page.wait_for_function("document.querySelector('#queuedNativeResult').textContent.includes('test-publication')")
            page.evaluate("state.cls='druid';state.level=11;renderQueuedNativeView()")
            assert 'test-publication' not in page.locator('#queuedNativeResult').inner_text()
            page.evaluate("state.cls='mage';state.level=10;window.__g50i.error=true;nativeQueueJob.state='checking';nativeQueueJob.failures=0")
            for _ in range(3):page.evaluate('pollNativeQueueStatus()')
            page.wait_for_function("document.querySelector('#queuedNativeStatus').textContent.includes('connection_lost')")
            assert page.locator('#retryQueuedNative').is_visible()
            page.evaluate("window.__g50i.error=false")
            page.click('#retryQueuedNative')
            page.wait_for_function("document.querySelector('#queuedNativeStatus').textContent.includes('completed')")
            assert page.evaluate('window.__g50i.posts')==1 # no automatic retry/requeue
            page.evaluate("window.__g50i.status='failed';nativeQueueJob.state='running'")
            page.evaluate('pollNativeQueueStatus()')
            page.wait_for_function("document.querySelector('#queuedNativeStatus').textContent.includes('failed')")
            assert page.locator('#loadQueuedNative').is_disabled()
            assert page.evaluate('window.__g50i.posts')==1
        finally:
            browser.close()
