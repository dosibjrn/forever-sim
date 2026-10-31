"""G50g: explicit native queue Decision HTTP ownership, integrity, no fallback."""
import json
import os
from pathlib import Path
from threading import Thread
from urllib.request import urlopen
from urllib.error import HTTPError
import pytest

from src.service.models import JobRequest
from src.service.store import QueueStore
from src.service.scheduler import Scheduler
from src.service.http_api import OptimizerHTTPServer
from src.service.publication import (read_current_queued_generic_decision,
                                     QueuedGenericDecisionUnavailable, current_publication)
from src.service.client import ServiceClient
from src.version import SOFTWARE_VERSION


def http_json(url):
    try:
        with urlopen(url,timeout=10) as response:
            return response.status,json.load(response)
    except HTTPError as exc:
        return exc.code,json.load(exc)


def real_publication(tmp_path):
    request=JobRequest(ruleset='forever',class_name='druid',start_level=10,end_level=10,
                       objective='endpoint',endpoint_mode='generic_decision',
                       forever_build_as_of='2026-10-08')
    store=QueueStore(tmp_path/'q.sqlite3')
    job,created=store.enqueue(request)
    assert created
    outcome=Scheduler(store,runs_root=tmp_path/'runs').run_once(project_root=tmp_path)
    assert outcome['state']=='completed',outcome
    return store,job,current_publication(tmp_path)


def test_live_queue_publication_service_and_listener_explicit_read(tmp_path,monkeypatch):
    import src.listener as listener
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    store,job,pub=real_publication(tmp_path)
    service=OptimizerHTTPServer(('127.0.0.1',0),store,project_root=tmp_path)
    service_thread=Thread(target=service.serve_forever,daemon=True);service_thread.start()
    base=f'http://127.0.0.1:{service.server_address[1]}'
    monkeypatch.setattr(listener,'_SERVICE_CLIENT',ServiceClient(base,timeout=4))
    from http.server import ThreadingHTTPServer
    ui=ThreadingHTTPServer(('127.0.0.1',0),listener.Handler)
    ui_thread=Thread(target=ui.serve_forever,daemon=True);ui_thread.start()
    ui_base=f'http://127.0.0.1:{ui.server_address[1]}'
    path='?backend=generic&class=druid&level=10'
    try:
        status,service_payload=http_json(base+'/api/v1/decisions/queued'+path)
        assert status==200,service_payload
        assert service_payload['publication_id']==pub['id']
        assert service_payload['decision']['identity']['level']==10
        assert service_payload['producer_version']==SOFTWARE_VERSION
        assert service_payload['authority']=='queued_native_generic_decision'
        status,ui_payload=http_json(ui_base+'/api/decisions/queued'+path)
        assert status==200 and ui_payload==service_payload
        assert 'decisions' not in ui_payload and ui_payload['legacy_fallback'] is False
        status,html=http_json_maybe_html(ui_base+'/decisions')
        assert status==200
        assert 'Inspect queued result' in html and 'queuedNativeResult' in html
        # No valid queue promotion for unsupported identity even when current exists.
        for query in ('?backend=legacy&class=druid&level=10',
                      '?backend=generic&class=mage&level=12',
                      '?backend=generic&class=druid&level=20',
                      '?class=druid&level=10'):
            code,_=http_json(base+'/api/v1/decisions/queued'+query)
            assert code==400,query
            code,_=http_json(ui_base+'/api/decisions/queued'+query)
            assert code==400,query
        # Corrupt-after-commit must fail closed through BOTH network hops.
        artifact=Path(pub['state_root'])/'generic/decisions/forever-druid-L10.json'
        original=artifact.read_bytes()
        try:
            artifact.write_bytes(original+b' ')
            service_status,_=http_json(base+'/api/v1/decisions/queued'+path)
            listener_status,listener_error=http_json(ui_base+'/api/decisions/queued'+path)
            assert service_status==409
            assert listener_status==503 and listener_error['legacy_fallback'] is False
        finally:
            artifact.write_bytes(original)
        # Missing current authority must NOT fall back to a local/offline result.
        pointer=tmp_path/'state/service/publication_current.json'
        old_pointer=pointer.read_bytes()
        try:
            pointer.unlink()
            service_status,_=http_json(base+'/api/v1/decisions/queued'+path)
            listener_status,_=http_json(ui_base+'/api/decisions/queued'+path)
            assert (service_status,listener_status)==(409,503)
        finally:
            pointer.write_bytes(old_pointer)
    finally:
        ui.shutdown();ui.server_close();ui_thread.join(timeout=5)
        service.shutdown();service.server_close();service_thread.join(timeout=5)


def http_json_maybe_html(url):
    with urlopen(url,timeout=8) as response:
        return response.status,response.read().decode()


def test_queued_read_rejects_unpublished_stale_and_tampered(tmp_path,monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    with pytest.raises(QueuedGenericDecisionUnavailable):
        read_current_queued_generic_decision(tmp_path,class_name='druid',level=10,backend='generic')
    _,job,pub=real_publication(tmp_path)
    result=read_current_queued_generic_decision(tmp_path,class_name='druid',level=10,backend='generic')
    assert result['job_id']==job['id']
    artifact=Path(pub['state_root'])/'generic/decisions/forever-druid-L10.json'
    original=artifact.read_bytes()
    try:
        payload=json.loads(original)
        payload['decision']['objective']['status']='injected'
        artifact.write_text(json.dumps(payload))
        with pytest.raises(QueuedGenericDecisionUnavailable,match='hash mismatch'):
            read_current_queued_generic_decision(tmp_path,class_name='druid',level=10,backend='generic')
    finally:
        artifact.write_bytes(original)
    # No traversal to an older generic overlay if another generation becomes current.
    root=tmp_path/'state/service'
    older=json.loads((root/'publication_current.json').read_text())
    legacy=dict(pub);legacy['id']='legacy-current';legacy['request']=dict(pub['request'],endpoint_mode='smooth')
    (root/'publications/legacy-current.json').write_text(json.dumps(legacy))
    (root/'publication_current.json').write_text(json.dumps({'publication_id':'legacy-current'}))
    with pytest.raises(QueuedGenericDecisionUnavailable,match='not a native generic'):
        read_current_queued_generic_decision(tmp_path,class_name='druid',level=10,backend='generic')
    (root/'publication_current.json').write_text(json.dumps(older))
    assert read_current_queued_generic_decision(tmp_path,class_name='druid',level=10,backend='generic')['publication_id']==pub['id']


def test_browser_explicit_queued_button_never_replaces_main_backend():
    from src.listener import DECISIONS_HTML
    from playwright.sync_api import sync_playwright
    html=DECISIONS_HTML.replace('<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>','')
    html=html.replace("load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);",'// G50g test initializes explicitly')
    html=html.replace('localStorage.','window.__g50gStorage.')
    html=html.replace('<head>','<head><script>window.__g50gStorage={getItem:()=>null,setItem:()=>{}};</script>',1)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,
                                   args=['--no-sandbox','--disable-dev-shm-usage','--disable-background-networking'])
        try:
            page=browser.new_page();page.set_content(html,wait_until='domcontentloaded')
            page.evaluate('''() => {
                state.cls='druid';state.level=10;state.backend='generic';
                data={active_backend:'generic',decisions:[],class_metadata:{druid:{queued_native_decision_levels:[10,11]},mage:{queued_native_decision_levels:[10]}}};
                window.fetch=async (url)=>({ok:true,status:200,json:async()=>({
                    authority:'queued_native_generic_decision',legacy_fallback:false,
                    execution_authority:'native_generic_decision',publication_id:'immutable-abc',
                    decision:{identity:{class_name:'druid',level:10},
                        backend:{id:'generic',version:'0.11.48.188'},
                        provenance:{source:'generic_backend_native',legacy_fallback:false},
                        objective:{status:'runtime_probe',mobs_per_hour:null}}
                })});
                renderQueuedNativeView();
                document.querySelector('#loadQueuedNative').addEventListener('click',loadQueuedNativeDecision);
            }''')
            page.click('#loadQueuedNative')
            page.wait_for_function("document.querySelector('#queuedNativeResult').innerText.includes('immutable-abc')")
            assert 'Source-only queued Decision' in page.locator('#queuedNativeResult').inner_text()
            assert page.evaluate("data.active_backend")=='generic'
            # Current class changed: old Druid publication cannot appear in Mage view.
            page.evaluate("state.cls='mage';renderQueuedNativeView()")
            assert not page.locator('#loadQueuedNative').is_disabled()
            assert 'immutable-abc' not in page.locator('#queuedNativeResult').inner_text()
        finally:
            browser.close()
