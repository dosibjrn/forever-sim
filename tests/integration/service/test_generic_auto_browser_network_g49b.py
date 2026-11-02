"""G49b: real Chromium UI + real listener/service HTTP via sandbox relay.

The environment blocks browser navigation with ERR_BLOCKED_BY_ADMINISTRATOR.
Only browser transport/storage are shimmed; response bytes come from real HTTP
servers, selection is real, and production UI code runs in Chromium. This is
NOT a direct browser-socket network E2E test.
"""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from src import listener
from src.game.data.forever import registry
from src.service import http_api
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src.v2.backend_selection import select_backend
from src.version import SOFTWARE_VERSION


def test_g49b_browser_auto_manual_persistence_and_fail_closed(monkeypatch, tmp_path):
    from playwright.sync_api import sync_playwright

    assert tuple(map(int, SOFTWARE_VERSION.split('.'))) >= (0, 11, 48, 178)
    original = dict(registry._PROVIDER_SUPPORT['druid'])
    monkeypatch.setitem(registry._PROVIDER_SUPPORT, 'druid', {
        **original, 'product_capabilities': {k: True for k in registry._DEFAULT_REQUIRED},
        'default_ready_levels': (10,),
    })
    fail = {'generic': False, 'mismatch': False, 'wrong_class': False,
            'wrong_level': False, 'wrong_selected_level': False, 'false_eligible': False}
    service_calls = []

    def selector_payload(project_root=None, selected_level=None, backend_id=None, class_name=None):
        choice = select_backend(requested=backend_id, class_key=class_name, level=selected_level)
        service_calls.append((choice['backend'], choice['mode'], choice['class_name'], choice['level']))
        if choice['backend'] == 'generic' and fail['generic']:
            raise RuntimeError('injected generic service failure')
        metadata = registry.generic_class_metadata(selected_level=choice['level'])
        metadata['paladin'] = {'display_name': 'Paladin', 'proof_only': False}
        selection = dict(choice)
        if fail['wrong_class']:
            selection['class_name'] = 'rogue'
        if fail['wrong_level']:
            selection['level'] = choice['level'] + 1
        if fail['false_eligible']:
            selection['generic_default_eligible'] = False
        return {
            'active_backend': ('legacy' if choice['backend'] == 'generic' and fail['mismatch'] else choice['backend']),
            'backend_selection': selection,
            'backends': [{'id': n, 'status': 'available'} for n in ('legacy','generic','compare')],
            'class_metadata': metadata,
            'product_surface': {'route_navigation': False, 'note': 'G49b network gate'},
            'selected_level': choice['level'] + int(fail['wrong_selected_level']), 'levels': [choice['level']],
            'decisions': [], 'cards': [], 'comparisons': [],
            'endpoint_paths': {}, 'spec_matrix': {}, 'route_rows': {},
            'per_level_rows': {}, 'reference_builds': {},
        }

    # Only expensive combat publication is stubbed, NOT backend selection or
    # the HTTP service, listener, client, browser app, or its event handlers.
    monkeypatch.setattr(http_api, 'build_decision_payload', selector_payload)
    remote = '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>'
    monkeypatch.setattr(listener, 'DECISIONS_HTML', listener.DECISIONS_HTML.replace(remote, ''))
    monkeypatch.delenv('WOW_LISTENER_OFFLINE_DECISIONS', raising=False)
    servers, threads = [], []

    def start(server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server); threads.append(thread)
        return f'http://127.0.0.1:{server.server_address[1]}'

    try:
        service_url = start(OptimizerHTTPServer(('127.0.0.1', 0), QueueStore(tmp_path/'queue.sqlite3')))
        monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(service_url, timeout=2))
        listener_url = start(ThreadingHTTPServer(('127.0.0.1', 0), listener.Handler))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'])
            try:
                page = None
                errors, decision_responses, decision_requests = [], [], []

                def relay(source, req):
                    url = urljoin(listener_url + '/', req['path'])
                    assert url.startswith(listener_url + '/'), url
                    if '/api/decisions?' in url:
                        decision_requests.append(url)
                    body = req.get('body')
                    request = Request(url, data=body.encode() if body else None,
                                      method=req.get('method') or 'GET')
                    try:
                        with urlopen(request, timeout=10) as response:
                            status, response_body = response.status, response.read().decode()
                    except HTTPError as exc:
                        status, response_body = exc.code, exc.read().decode()
                    if '/api/decisions?' in url:
                        decision_responses.append((url, status))
                    return {'status': status, 'body': response_body}

                store = {'foreverDecisionClass': 'druid', 'foreverDecisionLevel': '10',
                         'foreverDecisionBackendExplicit': '0'}

                def render_browser():
                    nonlocal page
                    if page is not None:
                        page.close()
                    page = browser.new_page()
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.expose_binding('__relayHttp', relay)
                    # Preserve the app's JS. Only transport and storage are
                    # replaced because about:blank cannot access localStorage
                    # and sandbox Chromium cannot access HTTP sockets.
                    prefix = ("<script>"
                        "window.__g49Store=new Map(__STORE__);"
                        "window.__g49Storage={getItem:k=>window.__g49Store.get(k)??null,"
                        "setItem:(k,v)=>window.__g49Store.set(k,String(v))};"
                        "window.fetch=async (url,opts={})=>{"
                        "const r=await window.__relayHttp({path:String(url),method:opts.method||'GET',body:opts.body||null});"
                        "return {ok:r.status>=200&&r.status<300,status:r.status,json:async()=>JSON.parse(r.body)};};"
                        "</script>").replace('__STORE__', json.dumps(list(store.items())))
                    html = listener.DECISIONS_HTML.replace('localStorage.', 'window.__g49Storage.')
                    html = html.replace('<head>', '<head>' + prefix, 1)
                    page.set_content(html, wait_until='domcontentloaded', timeout=12000)

                render_browser()
                page.wait_for_function("() => data?.active_backend==='generic' && data?.backend_selection?.mode==='automatic'", timeout=15000)
                assert page.locator('#backendPick').input_value() == 'auto'
                assert page.locator('#classPick').input_value() == 'druid'
                assert any('class=druid&level=10' in u for u in decision_requests)
                assert any(code == 200 for _, code in decision_responses)
                assert page.evaluate("window.__g49Storage.getItem('foreverDecisionBackendExplicit')") == '0'

                page.locator('#classPick').select_option('paladin')
                page.wait_for_function("() => data?.active_backend==='legacy' && data?.backend_selection?.class_name==='paladin'")
                assert page.locator('#backendPick').input_value() == 'auto'
                page.locator('#classPick').select_option('druid')
                page.wait_for_function("() => data?.active_backend==='generic' && data?.backend_selection?.class_name==='druid'")

                for backend in ('legacy', 'compare', 'generic'):
                    page.locator('#backendPick').select_option(backend)
                    page.wait_for_function('(b) => data?.active_backend===b && data?.backend_selection?.mode==="explicit"', arg=backend)
                    assert page.locator('#backendPick').input_value() == backend
                assert page.evaluate("window.__g49Storage.getItem('foreverDecisionBackendExplicit')") == '1'
                store = dict(page.evaluate('Array.from(window.__g49Store.entries())'))
                render_browser()
                page.wait_for_function("() => data?.active_backend==='generic' && data?.backend_selection?.mode==='explicit'")
                page.wait_for_function("() => document.querySelector('#backendPick')?.value==='generic'", timeout=15000)
                page.locator('#backendPick').select_option('auto')
                page.wait_for_function("() => data?.active_backend==='generic' && data?.backend_selection?.mode==='automatic'")
                store = dict(page.evaluate('Array.from(window.__g49Store.entries())'))
                render_browser()
                page.wait_for_function("() => data?.active_backend==='generic' && data?.backend_selection?.mode==='automatic'")
                page.wait_for_function("() => document.querySelector('#backendPick')?.value==='auto'", timeout=15000)

                before = len(decision_requests)
                fail['generic'] = True
                page.evaluate('reloadDecisions()')
                page.locator('#retryDecisionLoad').wait_for(timeout=15000)
                assert 'Decision loading failed' in page.locator('#backendPublication').inner_text()
                assert 'HTTP 503' in page.locator('#backendPublication').inner_text()
                assert page.evaluate('data?.active_backend') == 'generic'
                assert any(code == 503 for _, code in decision_responses)
                assert all('backend=legacy' not in u for u in decision_requests[before:])
                assert all(c[0] != 'legacy' for c in service_calls[-1:])
                fail['generic'] = False
                page.locator('#retryDecisionLoad').click()
                page.wait_for_function("() => data?.active_backend==='generic' && !document.querySelector('#retryDecisionLoad')", timeout=15000)
                # Even a 200 response is rejected if the selected backend and
                # published backend disagree (a silent-fallback regression).
                fail['mismatch'] = True
                page.evaluate('reloadDecisions()')
                page.locator('#retryDecisionLoad').wait_for(timeout=15000)
                assert 'backend selection authority mismatch' in page.locator('#backendPublication').inner_text()
                assert page.evaluate('data?.active_backend') == 'generic'
                fail['mismatch'] = False
                page.locator('#retryDecisionLoad').click()
                page.wait_for_function("() => data?.active_backend==='generic' && !document.querySelector('#retryDecisionLoad')", timeout=15000)
                # G49c: HTTP 200 with correct backend but incorrect request
                # identity/eligibility is still fail-closed; old data retained.
                for defect in ('wrong_class', 'wrong_level', 'wrong_selected_level', 'false_eligible'):
                    fail[defect] = True
                    page.evaluate('reloadDecisions()')
                    page.locator('#retryDecisionLoad').wait_for(timeout=15000)
                    assert 'backend selection authority mismatch' in page.locator('#backendPublication').inner_text()
                    assert page.evaluate("data?.backend_selection?.class_name") == 'druid'
                    assert page.evaluate("data?.selected_level") == 10
                    fail[defect] = False
                    page.locator('#retryDecisionLoad').click()
                    page.wait_for_function("() => !document.querySelector('#retryDecisionLoad')", timeout=15000)
                page.locator('#backendPick').select_option('compare')
                page.wait_for_function("() => data?.active_backend==='compare' && data?.backend_selection?.mode==='explicit'")
                assert any('backend=compare&class=druid&level=10' in u for u in decision_requests)
                page.locator('#backendPick').select_option('auto')
                page.wait_for_function("() => data?.active_backend==='generic' && data?.backend_selection?.mode==='automatic'")
                # G49c: an in-flight explicit response must not replace data
                # after a local class switch that intentionally does not fetch.
                page.locator('#backendPick').select_option('generic')
                page.wait_for_function("() => data?.backend_selection?.mode==='explicit'")
                page.evaluate('''() => {
                    window.__priorG49Data=data;window.__originalG49Fetch=window.fetch;
                    window.fetch=(...args)=>new Promise(resolve=>{
                        window.__releaseG49=()=>window.__originalG49Fetch(...args).then(resolve);
                    });
                    void reloadDecisions();
                }''')
                page.wait_for_function("() => typeof window.__releaseG49==='function'")
                page.locator('#classPick').select_option('paladin')
                assert page.evaluate("state.cls==='paladin'")
                page.evaluate('window.__releaseG49()')
                page.wait_for_timeout(250)
                assert page.evaluate('data===window.__priorG49Data')
                page.evaluate('window.fetch=window.__originalG49Fetch')
                page.locator('#backendPick').select_option('auto')
                page.wait_for_function("() => data?.active_backend==='legacy' && data?.backend_selection?.class_name==='paladin'")
                assert not errors, errors
                assert any('backend=compare' in u for u in decision_requests)
                assert any('backend=generic' in u for u in decision_requests)
                assert any('class=paladin' in u for u in decision_requests)
            finally:
                browser.close()
    finally:
        for server in servers:
            server.shutdown(); server.server_close()
        for thread in threads:
            thread.join(timeout=3)


def test_g49b_real_auto_promoted_generic_http_never_reads_legacy(monkeypatch, tmp_path):
    """No stubbed combat builder: real 7-class generic publication over two HTTP hops."""
    original = dict(registry._PROVIDER_SUPPORT['druid'])
    monkeypatch.setitem(registry._PROVIDER_SUPPORT, 'druid', {
        **original, 'product_capabilities': {k: True for k in registry._DEFAULT_REQUIRED},
        'default_ready_levels': (10,),
    })
    from src.v2 import decision_dashboard

    def forbid_legacy(*args, **kwargs):
        raise AssertionError('auto promoted generic must never read legacy publication')
    monkeypatch.setattr(decision_dashboard, 'read_published_class_artifact', forbid_legacy)
    monkeypatch.delenv('WOW_LISTENER_OFFLINE_DECISIONS', raising=False)
    servers, threads = [], []

    def start(server):
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start(); servers.append(server); threads.append(t)
        return f'http://127.0.0.1:{server.server_address[1]}'

    try:
        service = start(OptimizerHTTPServer(('127.0.0.1', 0), QueueStore(tmp_path/'real.sqlite3')))
        monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(service, timeout=2))
        proxy = start(ThreadingHTTPServer(('127.0.0.1', 0), listener.Handler))
        with urlopen(proxy + '/api/decisions?class=druid&level=10', timeout=60) as r:
            payload = json.load(r)
        assert payload['active_backend'] == 'generic'
        assert payload['backend_selection']['mode'] == 'automatic'
        assert payload['backend_selection']['generic_default_eligible'] is True
        assert payload['backend_selection']['legacy_fallback'] is False
        assert len(payload['decisions']) == len(registry.registered_class_keys())
        assert all(r['provenance']['legacy_fallback'] is False for r in payload['decisions'])
        assert payload['selected_level'] == 10
    finally:
        for server in servers:
            server.shutdown(); server.server_close()
        for t in threads:
            t.join(timeout=3)
