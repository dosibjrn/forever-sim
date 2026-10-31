"""G50h: exact provider declarations govern queue admission through HTTP/read."""
import json
import os
from pathlib import Path
import sys
from threading import Thread

import pytest

from src.game.data.forever.queue_capabilities import (
    PINNED_FOREVER_AS_OF, native_generic_queue_levels,
    native_generic_queue_artifact, require_native_generic_queue,
)
from src.game.data.forever.registry import registered_class_keys, generic_source_level_bounds
from src.service.executors import executor_for
from src.service.models import JobRequest
from src.service.store import QueueStore
from src.service.scheduler import Scheduler
from src.service.publication import (
    current_publication, read_current_queued_generic_decision,
    QueuedGenericDecisionUnavailable,
)
from src.service.http_api import OptimizerHTTPServer
from src.service.client import ServiceClient
from src.v2.decision_dashboard import _generic_ui_metadata
from src.version import SOFTWARE_VERSION
from tests.test_g50c_cold_service_http_isolation import _guard_environment
from tests.test_g50e_worker_child_legacy_boundary import _interpreter_guard_shim
from tests.test_g50g_explicit_queued_decision_read import http_json


def request(cls='druid', level=10):
    return JobRequest(ruleset='forever', class_name=cls, start_level=level,
        end_level=level, objective='endpoint', endpoint_mode='generic_decision',
        forever_build_as_of=PINNED_FOREVER_AS_OF)


def test_registry_declares_exact_source_only_queue_capabilities(monkeypatch):
    expected={'druid':(10,11),'warrior':(10,),'rogue':(10,),
              'priest':(10,),'shaman':(10,),'warlock':(10,),'mage':(10,)}
    assert set(registered_class_keys()) == set(expected)
    for cls, levels in expected.items():
        assert native_generic_queue_levels(cls) == levels
        bounds = generic_source_level_bounds(cls)
        assert all(bounds[0]<=n<=bounds[1] for n in levels)
        for n in levels:
            assert require_native_generic_queue(cls,n)==cls
            assert native_generic_queue_artifact(cls,n).as_posix() == f'generic/decisions/forever-{cls}-L{n}.json'
            plan=executor_for({'request':request(cls,n).canonical_dict()}).plan({'request':request(cls,n).canonical_dict()})
            assert plan.execution_authority=='native_generic_decision'
            assert plan.native_generic_job_supported is True
            assert plan.command[-6:]==['--class',cls,'--level',str(n),'--as-of',PINNED_FOREVER_AS_OF]
        assert _generic_ui_metadata(selected_level=10)[cls]['queued_native_decision_levels']==list(levels)
    for cls,n in [('druid',9),('druid',12),('warrior',11),('mage',11),('unknown',10),('../mage',10)]:
        with pytest.raises(ValueError): require_native_generic_queue(cls,n)
    from src.game.data.forever import queue_capabilities as qc
    monkeypatch.setitem(qc._DECLARED_QUEUE_LEVELS, 'mage', (10,21))
    assert native_generic_queue_levels('mage') == () # entire invalid declaration refused
    assert _generic_ui_metadata(selected_level=10)['mage']['queued_native_decision_levels'] == []


@pytest.mark.parametrize('cls,level', [('druid',11),('mage',10),('shaman',10),('warrior',10)])
def test_real_guarded_native_child_and_hashed_read_for_several_classes(tmp_path,monkeypatch,cls,level):
    store=QueueStore(tmp_path/'queue.sqlite3')
    job,created=store.enqueue(request(cls,level))
    assert created
    env,audit=_guard_environment(tmp_path,'native_imports.log')
    shim=_interpreter_guard_shim(tmp_path)
    monkeypatch.setattr(sys,'executable',str(shim))
    for key in ('PYTHONPATH','WOW_G50C_GUARD_SCRIPT','WOW_G50C_IMPORT_AUDIT','WOW_DISABLE_LEGACY_DECISIONS'):
        monkeypatch.setenv(key,env[key])
    monkeypatch.setenv('WOW_DISABLE_LEGACY_JOB_EXECUTION','1')
    result=Scheduler(store,runs_root=tmp_path/'runs').run_once(project_root=tmp_path)
    assert result['state']=='completed',result
    pub=current_publication(tmp_path)
    assert pub['request']['class_name']==cls
    path=Path(pub['state_root'])/native_generic_queue_artifact(cls,level)
    record=json.loads(path.read_text())['decision']
    assert record['identity']['class_name']==cls
    assert record['identity']['level']==level
    assert record['backend']['id']=='generic'
    assert record['provenance']['legacy_fallback'] is False
    assert audit.exists() and 'GUARD_LOADED:' in audit.read_text()
    assert 'BLOCKED:' not in audit.read_text(),audit.read_text()
    loaded=read_current_queued_generic_decision(tmp_path,class_name=cls,level=level,backend='generic')
    assert loaded['decision']==record and loaded['publication_id']==pub['id']
    wrong_cls='mage' if cls!='mage' else 'warrior'
    with pytest.raises(QueuedGenericDecisionUnavailable,match='different class/level'):
        read_current_queued_generic_decision(tmp_path,class_name=wrong_cls,level=10,backend='generic')
    original=path.read_bytes()
    try:
        path.write_bytes(original+b'\n')
        with pytest.raises(QueuedGenericDecisionUnavailable,match='hash mismatch'):
            read_current_queued_generic_decision(tmp_path,class_name=cls,level=level,backend='generic')
    finally:
        path.write_bytes(original)


def test_http_admission_and_queued_read_across_service_listener_for_mage(tmp_path,monkeypatch):
    import src.listener as listener
    monkeypatch.setenv('PYTHONPATH',str(Path(__file__).resolve().parents[1]))
    store=QueueStore(tmp_path/'queue.sqlite3')
    job,_=store.enqueue(request('mage',10))
    result=Scheduler(store,runs_root=tmp_path/'runs').run_once(project_root=tmp_path)
    assert result['state']=='completed',result
    service=OptimizerHTTPServer(('127.0.0.1',0),store,project_root=tmp_path)
    st=Thread(target=service.serve_forever,daemon=True);st.start()
    base=f'http://127.0.0.1:{service.server_address[1]}'
    monkeypatch.setattr(listener,'_SERVICE_CLIENT',ServiceClient(base,timeout=5))
    from http.server import ThreadingHTTPServer
    ui=ThreadingHTTPServer(('127.0.0.1',0),listener.Handler)
    ut=Thread(target=ui.serve_forever,daemon=True);ut.start()
    browser=f'http://127.0.0.1:{ui.server_address[1]}'
    try:
        q='?backend=generic&class=mage&level=10'
        sc,payload=http_json(base+'/api/v1/decisions/queued'+q)
        uc,proxied=http_json(browser+'/api/decisions/queued'+q)
        assert (sc,uc)==(200,200)
        assert payload==proxied and payload['decision']['identity']['class_name']=='mage'
        assert payload['decision']['backend']['version']==SOFTWARE_VERSION
        assert payload['legacy_fallback'] is False
        for q in ('?backend=generic&class=druid&level=10',
                  '?backend=generic&class=mage&level=11'):
            code,body=http_json(base+'/api/v1/decisions/queued'+q)
            assert code in (400,409),(code,body)
            proxy_code,_=http_json(browser+'/api/decisions/queued'+q)
            assert proxy_code in (400,503)
    finally:
        ui.shutdown();ui.server_close();ut.join(timeout=3)
        service.shutdown();service.server_close();st.join(timeout=3)


def test_browser_queue_inspector_uses_provider_capabilities_not_druid_branch():
    from src.listener import DECISIONS_HTML
    from playwright.sync_api import sync_playwright
    html=DECISIONS_HTML.replace('<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>','')
    html=html.replace("load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);",'// tested explicit state')
    html=html.replace('localStorage.','window.__g50hStorage.')
    html=html.replace('<head>','<head><script>window.__g50hStorage={getItem:()=>null,setItem:()=>{}};</script>',1)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,
                                   args=['--no-sandbox','--disable-dev-shm-usage','--disable-background-networking'])
        try:
            page=browser.new_page()
            page.set_content(html,wait_until='domcontentloaded')
            page.evaluate('''() => {
              data={active_backend:'generic',decisions:[],class_metadata:{
                druid:{queued_native_decision_levels:[10,11]},
                mage:{queued_native_decision_levels:[10]},
                warrior:{queued_native_decision_levels:[10]}}};
              state.cls='druid';state.level=11;state.backend='generic';
              window.fetch=async (url)=>({ok:true,status:200,json:async()=>({
                authority:'queued_native_generic_decision',legacy_fallback:false,
                execution_authority:'native_generic_decision',publication_id:'g50h-'+state.cls,
                decision:{identity:{class_name:state.cls,level:state.level},
                  backend:{id:'generic',version:'0.11.48.189'},
                  provenance:{source:'generic_backend_native',legacy_fallback:false},
                  objective:{status:'runtime_probe',mobs_per_hour:null}}
              })});
              document.querySelector('#loadQueuedNative').addEventListener('click',loadQueuedNativeDecision);
              renderQueuedNativeView();
            }''')
            assert not page.locator('#loadQueuedNative').is_disabled()
            page.click('#loadQueuedNative')
            page.wait_for_function("document.querySelector('#queuedNativeResult').innerText.includes('g50h-druid')")
            page.evaluate("state.cls='mage';state.level=10;renderQueuedNativeView()")
            assert not page.locator('#loadQueuedNative').is_disabled()
            assert 'g50h-druid' not in page.locator('#queuedNativeResult').inner_text()
            page.click('#loadQueuedNative')
            page.wait_for_function("document.querySelector('#queuedNativeResult').innerText.includes('g50h-mage')")
            page.evaluate("state.level=11;renderQueuedNativeView()")
            assert page.locator('#loadQueuedNative').is_disabled()
            assert 'g50h-mage' not in page.locator('#queuedNativeResult').inner_text()
            assert page.evaluate('data.active_backend')=='generic'
        finally:
            browser.close()
