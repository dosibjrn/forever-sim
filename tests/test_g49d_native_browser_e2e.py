"""G49d strict **native browser-socket** decision publication checkpoint.

This is intentionally not a Playwright HTTP relay. Browser navigates to the
real listener origin and uses its own network stack for all fetches. If the
runner prohibits loopback browser traffic, skip with an explicit explanation
(unless WOW_REQUIRE_NATIVE_BROWSER_E2E=1, which makes the gate fail closed).

Only the expensive decision *body* is stubbed to keep this integration bounded;
backend selection, listener, optimizer HTTP, browser routing, storage and JS
all run through the actual production implementations.
"""
import os
import threading
from http.server import ThreadingHTTPServer

import pytest

from src.game.data.forever import registry
from src.v2.backend_selection import select_backend


def test_g49d_unbridged_browser_listener_service_auto_and_fail_closed(monkeypatch, tmp_path):
    from playwright.sync_api import Error as PlaywrightError, sync_playwright
    from src import listener
    from src.service import http_api
    from src.service.client import ServiceClient
    from src.service.http_api import OptimizerHTTPServer
    from src.service.store import QueueStore

    original = dict(registry._PROVIDER_SUPPORT['druid'])
    monkeypatch.setitem(registry._PROVIDER_SUPPORT, 'druid', {
        **original,
        'product_capabilities': {key: True for key in registry._DEFAULT_REQUIRED},
        'default_ready_levels': (10,),
    })
    failures = {'service': False, 'mismatch': False}
    service_calls = []

    def decision_body(project_root=None, selected_level=None, backend_id=None, class_name=None):
        selection = select_backend(requested=backend_id, class_key=class_name, level=selected_level)
        service_calls.append((selection['backend'], selection['mode'], selection['class_name'], selection['level']))
        if failures['service'] and selection['backend'] == 'generic':
            raise RuntimeError('G49d intentional generic decision failure')
        return {
            'active_backend': 'legacy' if failures['mismatch'] and selection['backend'] == 'generic' else selection['backend'],
            'backend_selection': selection,
            'selected_level': selection['level'],
            'backends': [{'id': key, 'status': 'available'} for key in ('legacy','generic','compare')],
            'class_metadata': registry.generic_class_metadata(selected_level=selection['level']),
            'levels': [selection['level']],
            'decisions': [], 'cards': [], 'comparisons': [],
            'product_surface': {'route_navigation': False},
            'endpoint_paths': {}, 'spec_matrix': {}, 'route_rows': {},
            'per_level_rows': {}, 'reference_builds': {},
        }

    monkeypatch.setattr(http_api, 'build_decision_payload', decision_body)
    monkeypatch.delenv('WOW_LISTENER_OFFLINE_DECISIONS', raising=False)
    remote_tooltip = '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>'
    monkeypatch.setattr(listener, 'DECISIONS_HTML', listener.DECISIONS_HTML.replace(remote_tooltip, ''))
    servers, threads = [], []

    def start(server):
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        servers.append(server)
        threads.append(t)
        return f'http://127.0.0.1:{server.server_address[1]}'

    try:
        optimizer_url = start(OptimizerHTTPServer(('127.0.0.1', 0), QueueStore(tmp_path / 'queue.sqlite3')))
        monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(optimizer_url, timeout=3))
        listener_url = start(ThreadingHTTPServer(('127.0.0.1', 0), listener.Handler))
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=os.environ.get('WOW_CHROMIUM_EXECUTABLE', '/usr/bin/chromium'), headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'])
            try:
                context = browser.new_context()
                context.add_init_script('''(() => {
                    localStorage.setItem('foreverDecisionClass','druid');
                    localStorage.setItem('foreverDecisionLevel','10');
                    if (localStorage.getItem('foreverDecisionBackendExplicit') === null)
                        localStorage.setItem('foreverDecisionBackendExplicit','0');
                })();''')
                page = context.new_page()
                errors, browser_requests = [], []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('request', lambda request: browser_requests.append(request.url))
                try:
                    response = page.goto(listener_url + '/decisions', wait_until='domcontentloaded', timeout=7000)
                except PlaywrightError as exc:
                    if 'ERR_BLOCKED_BY_ADMINISTRATOR' in str(exc):
                        if os.environ.get('WOW_REQUIRE_NATIVE_BROWSER_E2E') == '1':
                            pytest.fail('Native browser socket blocked; mandatory G49d gate NOT PASS')
                        pytest.skip('G49d native browser socket blocked by runner policy; rerun in unrestricted Chromium environment with WOW_REQUIRE_NATIVE_BROWSER_E2E=1')
                    raise
                assert response.status == 200
                assert page.url.startswith(listener_url + '/decisions')
                page.wait_for_function('''() => data?.active_backend==='generic' &&
                    data.backend_selection?.mode==='automatic' &&
                    data.backend_selection?.class_name==='druid' ''', timeout=12000)
                assert any('/api/decisions?class=druid&level=10' in url for url in browser_requests), browser_requests
                assert ('generic', 'automatic', 'druid', 10) in service_calls
                page.locator('#classPick').select_option('paladin')
                page.wait_for_function("() => data?.active_backend==='legacy' && data?.backend_selection?.class_name==='paladin'", timeout=12000)
                page.locator('#classPick').select_option('druid')
                page.wait_for_function("() => data?.active_backend==='generic' && data?.backend_selection?.class_name==='druid'", timeout=12000)

                for explicit in ('legacy', 'compare', 'generic'):
                    page.locator('#backendPick').select_option(explicit)
                    page.wait_for_function('(b) => data?.active_backend===b && data?.backend_selection?.mode==="explicit"', arg=explicit, timeout=12000)
                assert any('/api/decisions?backend=generic&class=druid&level=10' in u for u in browser_requests)
                page.reload(wait_until='domcontentloaded', timeout=12000)
                page.wait_for_function("() => data?.active_backend==='generic' && data?.backend_selection?.mode==='explicit'", timeout=12000)
                page.locator('#backendPick').select_option('auto')
                page.wait_for_function("() => data?.active_backend==='generic' && data?.backend_selection?.mode==='automatic'", timeout=12000)

                before = len(browser_requests)
                failures['service'] = True
                page.evaluate('reloadDecisions()')
                page.locator('#retryDecisionLoad').wait_for(timeout=12000)
                assert 'HTTP 503' in page.locator('#backendPublication').inner_text()
                assert page.evaluate("data.active_backend") == 'generic'
                assert all('backend=legacy' not in u for u in browser_requests[before:])
                failures['service'] = False
                page.locator('#retryDecisionLoad').click()
                page.wait_for_function("() => !document.querySelector('#retryDecisionLoad')", timeout=12000)
                failures['mismatch'] = True
                page.evaluate('reloadDecisions()')
                page.locator('#retryDecisionLoad').wait_for(timeout=12000)
                assert 'backend selection authority mismatch' in page.locator('#backendPublication').inner_text()
                assert page.evaluate("data.active_backend") == 'generic'
                assert not errors, errors
            finally:
                browser.close()
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)
