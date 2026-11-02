"""G49a: backend default is an explicit product-capability decision, never fallback."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import pytest

from src.game.data.forever import registry
from src.v2.backend_selection import select_backend
from src.version import SOFTWARE_VERSION


def test_all_current_providers_fail_closed_and_manual_choices_remain_available():
    assert tuple(map(int, SOFTWARE_VERSION.split("."))) >= (0, 11, 48, 177)
    for cls in registry.registered_class_keys():
        assert registry.generic_default_ready_levels(cls) == ()
        for level in (10, 14, 20, 60):
            auto = select_backend(class_key=cls, level=level)
            assert auto['backend'] == 'legacy'
            assert auto['mode'] == 'automatic'
            assert auto['generic_default_eligible'] is False
            assert auto['legacy_fallback'] is False
    for backend in ('legacy', 'generic', 'compare'):
        row = select_backend(requested=backend, class_key='druid', level=10)
        assert row['backend'] == backend
        assert row['mode'] == 'explicit'
    with pytest.raises(ValueError, match='backend must be one of'):
        select_backend(requested='generic_or_legacy', class_key='druid', level=10)
    assert {'paladin', 'druid', 'warlock'} <= set(select_backend()['selectable_classes'])


def test_complete_exact_level_declaration_required(monkeypatch):
    key = 'druid'
    original = dict(registry._PROVIDER_SUPPORT[key])
    full = {name: True for name in registry._DEFAULT_REQUIRED}
    monkeypatch.setitem(registry._PROVIDER_SUPPORT, key, {
        **original, 'product_capabilities': full, 'default_ready_levels': (10, 11),
    })
    assert registry.generic_default_ready_levels(key) == (10, 11)
    assert select_backend(class_key=key, level=10)['backend'] == 'generic'
    assert select_backend(class_key=key, level=11)['backend'] == 'generic'
    assert select_backend(class_key=key, level=12)['backend'] == 'legacy'
    assert select_backend(class_key='warrior', level=10)['backend'] == 'legacy'
    assert select_backend(requested='legacy', class_key=key, level=10)['backend'] == 'legacy'
    assert select_backend(requested='compare', class_key=key, level=10)['backend'] == 'compare'
    metadata = registry.generic_class_metadata(selected_level=10)[key]
    assert metadata['default_ready_at_selected_level'] is True
    assert metadata['default_ready_levels'] == [10, 11]
    # A single missing dimension revokes *all* automatic authority.
    monkeypatch.setitem(registry._PROVIDER_SUPPORT, key, {
        **original, 'product_capabilities': {**full, 'stat_weights': False},
        'default_ready_levels': (10, 11),
    })
    assert select_backend(class_key=key, level=10)['backend'] == 'legacy'
    # Invalid declaration (outside route corridor) is not silently truncated.
    monkeypatch.setitem(registry._PROVIDER_SUPPORT, key, {
        **original, 'product_capabilities': full, 'default_ready_levels': (10, 20),
    })
    assert registry.generic_default_ready_levels(key) == ()



def test_actual_payload_auto_is_legacy_and_promoted_generic_never_reads_legacy(monkeypatch):
    from src.v2 import decision_dashboard as dashboard
    real = dashboard.build_decision_payload(selected_level=10, class_name='druid')
    assert real['active_backend'] == 'legacy'
    assert real['backend_selection']['mode'] == 'automatic'
    assert real['backend_selection']['generic_default_eligible'] is False

    original = dict(registry._PROVIDER_SUPPORT['druid'])
    monkeypatch.setitem(registry._PROVIDER_SUPPORT, 'druid', {
        **original, 'product_capabilities': {name: True for name in registry._DEFAULT_REQUIRED},
        'default_ready_levels': (10,),
    })
    def legacy_forbidden(*args, **kwargs):
        raise AssertionError('automatic generic execution read legacy artifacts')
    monkeypatch.setattr(dashboard, 'read_published_class_artifact', legacy_forbidden)
    monkeypatch.setattr(dashboard, '_generic_decision_payload',
                        lambda selected_level: {'active_backend': 'generic', 'decisions': []})
    promoted = dashboard.build_decision_payload(selected_level=10, class_name='druid')
    assert promoted['active_backend'] == 'generic'
    assert promoted['backend_selection']['reason'] == 'declared_product_complete_at_level'
    assert promoted['backend_selection']['legacy_fallback'] is False
    # Explicit generic must remain generic even when a different level is not
    # product-complete; no automatic fallback on a failed or partial capability.
    explicit = dashboard.build_decision_payload(selected_level=20, class_name='druid', backend_id='generic')
    assert explicit['active_backend'] == 'generic'
    assert explicit['backend_selection']['mode'] == 'explicit'
    assert explicit['backend_selection']['generic_default_eligible'] is False
    monkeypatch.setattr(dashboard, '_generic_decision_payload',
                        lambda selected_level: (_ for _ in ()).throw(RuntimeError('generic failed')))
    with pytest.raises(RuntimeError, match='generic failed'):
        dashboard.build_decision_payload(selected_level=10, class_name='druid')


def test_client_auto_query_has_no_backend_and_forwards_class(monkeypatch):
    from src.service.client import ServiceClient
    seen = []
    def fake(self, method, path, body=None, **kw):
        seen.append((method, path, kw.get('timeout')))
        return {'active_backend': 'legacy'}
    monkeypatch.setattr(ServiceClient, '_request', fake)
    c = ServiceClient()
    assert c.decisions(level=20, class_name='druid')['active_backend'] == 'legacy'
    assert seen[-1] == ('GET', '/api/v1/decisions?level=20&class=druid', 65.0)
    c.decisions(level=20, backend_id='compare')
    assert seen[-1] == ('GET', '/api/v1/decisions?backend=compare&level=20', 15.0)


def test_service_listener_http_parity_for_automatic_and_explicit(monkeypatch, tmp_path):
    from src.service.http_api import OptimizerHTTPServer
    from src.service.store import QueueStore
    from src.service.client import ServiceClient
    from src.service import http_api
    from src import listener

    # Keep the real two HTTP hops, query parser, client and selection authority;
    # stub the unrelated costly combat publication in this selector test.
    def lightweight_payload(project_root=None, selected_level=None, backend_id=None, class_name=None):
        choice = select_backend(requested=backend_id, class_key=class_name, level=selected_level)
        return {'active_backend': choice['backend'], 'backend_selection': choice}
    monkeypatch.setattr(http_api, 'build_decision_payload', lightweight_payload)
    servers, threads = [], []
    def start(server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start(); servers.append(server); threads.append(thread)
        return f'http://127.0.0.1:{server.server_address[1]}'
    try:
        service = start(OptimizerHTTPServer(('127.0.0.1', 0), QueueStore(tmp_path/'queue.sqlite3')))
        monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(service, timeout=2))
        proxy = start(ThreadingHTTPServer(('127.0.0.1', 0), listener.Handler))
        paths = ('?class=druid&level=10', '?backend=generic&level=10',
                 '?backend=compare&level=10', '?backend=legacy&level=10')
        for suffix, backend in zip(paths, ('legacy', 'generic', 'compare', 'legacy')):
            with urlopen(service + '/api/v1/decisions' + suffix, timeout=6) as response:
                direct = json.load(response)
            with urlopen(proxy + '/api/decisions' + suffix, timeout=6) as response:
                forwarded = json.load(response)
            assert direct == forwarded
            assert direct['active_backend'] == backend
            assert direct['backend_selection']['mode'] == ('automatic' if 'backend=' not in suffix else 'explicit')
    finally:
        for server in servers: server.shutdown(); server.server_close()
        for thread in threads: thread.join(timeout=3)



def test_actual_legacy_auto_service_listener_http(monkeypatch, tmp_path):
    from src.service.http_api import OptimizerHTTPServer
    from src.service.store import QueueStore
    from src.service.client import ServiceClient
    from src import listener
    servers, threads = [], []
    def start(server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start(); servers.append(server); threads.append(thread)
        return f'http://127.0.0.1:{server.server_address[1]}'
    try:
        service = start(OptimizerHTTPServer(('127.0.0.1', 0), QueueStore(tmp_path/'queue.sqlite3')))
        monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(service, timeout=2))
        proxy = start(ThreadingHTTPServer(('127.0.0.1', 0), listener.Handler))
        path = '?class=druid&level=10'  # no backend override
        with urlopen(service + '/api/v1/decisions' + path, timeout=10) as response:
            direct = json.load(response)
        with urlopen(proxy + '/api/decisions' + path, timeout=10) as response:
            forwarded = json.load(response)
        assert forwarded == direct
        assert forwarded['active_backend'] == 'legacy'
        assert forwarded['backend_selection']['mode'] == 'automatic'
        assert forwarded['backend_selection']['generic_default_eligible'] is False
        assert len(forwarded['decisions']) > 0
    finally:
        for server in servers: server.shutdown(); server.server_close()
        for thread in threads: thread.join(timeout=3)


def test_browser_auto_can_switch_classes_and_explicit_override():
    from src.listener import DECISIONS_HTML
    from playwright.sync_api import sync_playwright

    html = DECISIONS_HTML.replace(
        '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>', ''
    ).replace("load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);", '')
    html = html.replace('localStorage.', 'window.__g49Storage.').replace(
        '<head>', '<head><script>window.__g49Store=new Map();window.__g49Storage={getItem:k=>window.__g49Store.get(k)??null,setItem:(k,v)=>window.__g49Store.set(k,String(v))};</script>', 1
    )
    classes = ['druid', 'paladin', 'warlock']
    def payload(backend, cls):
        return {
            'active_backend': backend, 'backends': [{'id': n, 'status': 'available'} for n in ('legacy','generic','compare')],
            'backend_selection': {'backend': backend, 'mode': 'automatic', 'reason': 'capability-gated',
                                  'generic_default_eligible': backend == 'generic', 'legacy_fallback': False,
                                  'selectable_classes': classes},
            'class_metadata': {c: {'display_name': c.title(), 'source_ir_level_bounds': {'min':10,'max':20}}
                               for c in classes},
            'product_surface': {'route_navigation': False, 'note': 'G49a selection proof'},
            'selected_level': 20, 'levels': [20], 'decisions': [], 'cards': [],
            'endpoint_paths': {}, 'spec_matrix': {}, 'route_rows': {}, 'per_level_rows': {},
            'reference_builds': {}, 'comparisons': [],
        }
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'])
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda err: errors.append(str(err)))
            page.set_content(html, wait_until='domcontentloaded', timeout=12000)
            page.evaluate('''({legacy,generic,compare}) => {
                window.__calls=[];
                window.fetch=async url => {
                    window.__calls.push(String(url));
                    const u=new URL(String(url),'http://localhost');
                    const explicit=u.searchParams.get('backend');
                    const cls=u.searchParams.get('class')||state.cls;
                    const backend=explicit|| (cls==='druid'?'generic':'legacy');
                    const source=backend==='generic'?generic:(backend==='compare'?compare:legacy);
                    const response={...source,backend_selection:{...source.backend_selection,backend,
                      class_name:cls,level:Number(u.searchParams.get('level')||20),
                      mode:explicit?'explicit':'automatic',generic_default_eligible:cls==='druid',legacy_fallback:false}};
                    return {ok:true,json:async()=> response};
                };
                loadServiceStatus=()=>{};loadRuntimeStatus=()=>{};
                data=legacy;state.backend='legacy';state.cls='paladin';state.level=20;
                backendExplicit=false;syncState();renderAll();bind();
            }''', {'legacy':payload('legacy','paladin'), 'generic':payload('generic','druid'),
                    'compare':payload('compare','paladin')})
            assert page.locator('#backendPick').input_value() == 'auto'
            assert page.evaluate("window.__g49Storage.getItem('foreverDecisionBackendExplicit')") == '0'
            page.locator('#classPick').select_option('druid')
            page.wait_for_function("() => data?.active_backend==='generic'")
            assert page.locator('#backendPick').input_value() == 'auto'
            assert 'Paladin' in page.locator('#classPick').locator('option').all_text_contents()
            page.locator('#classPick').select_option('paladin')
            page.wait_for_function("() => data?.active_backend==='legacy'")
            page.locator('#backendPick').select_option('generic')
            page.wait_for_function("() => backendExplicit && data?.active_backend==='generic'")
            assert page.locator('#backendPick').input_value() == 'generic'
            assert page.evaluate("window.__g49Storage.getItem('foreverDecisionBackendExplicit')") == '1'
            page.locator('#backendPick').select_option('auto')
            page.wait_for_function("() => !backendExplicit && data?.active_backend==='legacy'")
            assert page.evaluate("window.__g49Storage.getItem('foreverDecisionBackendExplicit')") == '0'
            calls = page.evaluate('window.__calls')
            assert any('/api/decisions?class=druid' in x for x in calls)
            assert any('/api/decisions?backend=generic' in x for x in calls)
            assert any('/api/decisions?class=paladin' in x for x in calls)
            assert not errors, errors
        finally:
            browser.close()
