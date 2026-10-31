"""G49b browser-origin decision fetch crosses real listener and optimizer HTTP.

Chromium localhost navigation is prohibited in some sandboxes.  Only the
browser->listener socket is bridged by Playwright routing; listener->service,
HTTP handling, selection and error paths run on real sockets. No browser fetch
or backend-selection result is stubbed.
"""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

from src.game.data.forever import registry
from src.v2.backend_selection import select_backend


def test_browser_auto_promotion_explicit_override_and_fail_closed(monkeypatch, tmp_path):
    from src import listener
    from src.service import http_api
    from src.service.client import ServiceClient
    from src.service.http_api import OptimizerHTTPServer
    from src.service.store import QueueStore

    original = dict(registry._PROVIDER_SUPPORT['druid'])
    monkeypatch.setitem(registry._PROVIDER_SUPPORT, 'druid', {
        **original,
        'product_capabilities': {name: True for name in registry._DEFAULT_REQUIRED},
        'default_ready_levels': (10,),
    })
    failure = {'enabled': False}
    calls = []

    def service_payload(project_root=None, selected_level=None, backend_id=None, class_name=None):
        selection = select_backend(requested=backend_id, class_key=class_name, level=selected_level)
        if failure['enabled'] and selection['backend'] == 'generic':
            raise RuntimeError('injected generic publication failure')
        backend = selection['backend']
        return {
            'active_backend': backend, 'backend_selection': selection,
            'selected_level': selected_level or 10,
            'backends': [{'id': name, 'status': 'available'} for name in ('legacy','generic','compare')],
            'class_metadata': {cls: {'display_name': cls.title(),
                                    'source_ir_level_bounds': {'min': 10, 'max': 20}}
                               for cls in ('druid','paladin','mage')},
            'levels': [10], 'decisions': [], 'cards': [], 'product_surface': {'route_navigation': False},
            'endpoint_paths': {}, 'spec_matrix': {}, 'route_rows': {}, 'per_level_rows': {},
            'reference_builds': {}, 'comparisons': [],
        }
    monkeypatch.setattr(http_api, 'build_decision_payload', service_payload)

    servers, threads = [], []
    def start(server):
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start(); servers.append(server); threads.append(t)
        return f'http://127.0.0.1:{server.server_address[1]}'

    try:
        service = start(OptimizerHTTPServer(('127.0.0.1', 0), QueueStore(tmp_path/'q.sqlite3')))
        monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(service, timeout=3))
        proxy = start(ThreadingHTTPServer(('127.0.0.1', 0), listener.Handler))
        html = listener.DECISIONS_HTML.replace(
            '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>', ''
        ).replace("load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);", '')
        html = html.replace('localStorage.', 'window.__g49Storage.').replace(
            '<head>', '<head><script>window.__g49Store=new Map();window.__g49Storage={getItem:k=>window.__g49Store.get(k)??null,setItem:(k,v)=>window.__g49Store.set(k,String(v))};</script>', 1,
        )
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
                args=['--no-sandbox','--disable-dev-shm-usage','--disable-background-networking'])
            try:
                page = browser.new_page()
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                def bridge(route):
                    path = route.request.url.split('/api/decisions', 1)[1]
                    url = proxy + '/api/decisions' + path
                    try:
                        with urlopen(url, timeout=10) as r:
                            status, body = r.status, r.read()
                    except HTTPError as e:
                        status, body = e.code, e.read()
                    calls.append((route.request.url, status, json.loads(body)))
                    route.fulfill(status=status, body=body, content_type='application/json')
                page.route('**/api/decisions?*', bridge)
                # Browser network sandbox disallows direct localhost navigation;
                # the actual fetch is initiated from Chromium and routed to the
                # listener HTTP server with no fabricated response data.
                page.set_content(html.replace('<head>', f'<head><base href="{proxy}/">', 1),
                                 wait_until='domcontentloaded', timeout=12000)
                page.evaluate('payload => { window.__initialG49=payload; }', service_payload(selected_level=10, class_name='druid'))
                page.evaluate('''() => {
                    loadServiceStatus=()=>{};loadRuntimeStatus=()=>{};
                    data=window.__initialG49;state.cls='druid';state.level=10;state.backend='legacy';
                    backendExplicit=false;syncState();renderAll();bind();
                }''')
                page.evaluate('reloadDecisions()')
                assert page.evaluate('data.active_backend') == 'generic', (calls, page.locator('#backendPublication').inner_text()[:500], errors)
                assert calls[-1][2]['backend_selection']['generic_default_eligible'] is True
                assert calls[-1][2]['backend_selection']['legacy_fallback'] is False
                assert 'backend=' not in calls[-1][0]
                page.locator('#classPick').select_option('paladin')
                page.wait_for_function("() => data?.active_backend==='legacy'")
                assert calls[-1][2]['backend_selection']['mode'] == 'automatic'
                page.locator('#classPick').select_option('druid')
                page.wait_for_function("() => data?.active_backend==='generic'")
                page.locator('#backendPick').select_option('legacy')
                page.wait_for_function("() => data?.active_backend==='legacy' && backendExplicit")
                assert 'backend=legacy' in calls[-1][0]
                page.locator('#backendPick').select_option('auto')
                page.wait_for_function("() => data?.active_backend==='generic' && !backendExplicit")
                assert page.evaluate("window.__g49Storage.getItem('foreverDecisionBackendExplicit')") == '0'
                # A fresh generic publication failure must NOT return legacy.
                failure['enabled'] = True
                page.evaluate('reloadDecisions()')
                assert calls[-1][1] == 503
                assert calls[-1][2].get('offline_fallback') is False
                assert page.evaluate('data.active_backend') == 'generic'  # retained, not replaced
                assert page.locator('#backendPublication').inner_text().find('Decision loading failed') >= 0
                assert page.locator('#retryDecisionLoad').count() == 1
                assert not errors, errors
            finally:
                browser.close()
    finally:
        for server in servers:
            server.shutdown(); server.server_close()
        for thread in threads:
            thread.join(timeout=3)
