"""G48d: one real seven-class generic surface with source-only level navigation.

Route focus remains a native route-scored DecisionRecord. Classes without
routes can choose source-IR levels, which must load a fresh backend record;
no missing route, named gear or cross-class comparability is invented.
"""

import pytest
import os

from src.game.data.forever.registry import registered_class_keys
from src.listener import DECISIONS_HTML
from src.v2.decision_dashboard import _generic_decision_payload
from src.version import SOFTWARE_VERSION


@pytest.fixture(scope="module")
def snapshots():
    return {level: _generic_decision_payload(level) for level in (10, 20)}


def test_all_class_payload_gate(snapshots):
    assert tuple(map(int, SOFTWARE_VERSION.split("."))) >= (0, 11, 48, 176)
    assert "sourceOnlyLevelChange:true" in DECISIONS_HTML
    assert "sourceOnlyLevelChange===true||!explicit?60000:20000" in DECISIONS_HTML
    assert len(snapshots[10]["native_route_decisions"]) == 26
    keys = set(registered_class_keys())
    for level, payload in snapshots.items():
        records = {r["identity"]["class_name"]: r for r in payload["decisions"]}
        assert set(records) == keys
        assert payload["selected_level"] == level
        assert all(r["identity"]["level"] == level for r in records.values())
        assert all(r["provenance"]["legacy_fallback"] is False for r in records.values())
        for cls in keys:
            meta = payload["class_metadata"][cls]
            assert meta["selected_level_source_ir_available"] is True
            assert len(records[cls]["capability"]["publication_sections"]["sections"]) == 7
            if cls in {"mage", "priest", "shaman", "warlock"}:
                assert cls not in payload["route_rows"]
                assert meta["planning_levels"] == []
                assert records[cls]["publication_availability"]["route"] == "not_in_level_record"
                assert not any(r["identity"]["class_name"] == cls for r in payload["native_route_decisions"])
        for route_record in payload["native_route_decisions"]:
            assert route_record["identity"]["class_name"] in {"druid", "warrior", "rogue"}
            assert route_record["identity"]["route_scored"] is True
            assert route_record["objective"]["cross_class_comparable"] is False


def test_real_chromium_all_class_navigation_and_backend_level_refresh(snapshots):
    from playwright.sync_api import sync_playwright

    html = DECISIONS_HTML.replace(
        '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>', ''
    ).replace(
        "load().catch(e=>$('authority').textContent='Decisions unavailable: '+e);",
        '// G48d supplies real service-generated publications'
    ).replace('localStorage.', 'window.__g48Storage.').replace(
        '<head>', '<head><script>window.__g48Storage={getItem:()=>null,setItem:()=>{}};</script>', 1
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=os.environ.get('WOW_CHROMIUM_EXECUTABLE', '/usr/bin/chromium'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-background-networking'],
        )
        try:
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.set_content(html, wait_until='domcontentloaded', timeout=12000)
            page.evaluate('''({first,second}) => {
                window.__g48Calls=[];
                window.__g48Response=second;
                window.fetch=async url => {
                    window.__g48Calls.push(String(url));
                    if(window.__g48Fail) return {ok:false,status:503};
                    const u=new URL(String(url),'http://localhost');
                    return {ok:true,json:async()=>({...window.__g48Response,
                        backend_selection:{backend:'generic',mode:'explicit',
                            class_name:u.searchParams.get('class'),level:Number(u.searchParams.get('level')),
                            generic_default_eligible:false,legacy_fallback:false}})};
                };
                loadServiceStatus=()=>{};
                data=first;state.backend='generic';backendExplicit=true;state.cls='mage';
                state.target='';state.route='';state.level=NaN;
                syncState();renderAll();bind();
            }''', {'first': snapshots[10], 'second': snapshots[20]})

            # Every class uses the same real class picker and publication panel.
            for cls in registered_class_keys():
                page.locator('#classPick').select_option(cls)
                row = page.evaluate('''() => ({
                    cls:state.cls,level:state.level,
                    text:document.getElementById('backendPublication').innerText,
                    route:document.getElementById('nativeRouteDecision')?.innerText||'',
                    sourceOptions:document.getElementById('levelPick').options.length,
                    sourceDisabled:document.getElementById('levelPick').disabled,
                    routeVisible:document.querySelector('.route-product').style.display,
                })''')
                assert row['cls'] == cls
                assert 'Generic publication coverage' in row['text']
                assert 'Playable race selection: not verified' in row['text']
                if cls in {'mage', 'priest', 'shaman', 'warlock'}:
                    assert row['level'] == 10
                    assert row['sourceOptions'] == 11
                    assert row['sourceDisabled'] is False
                    assert row['routeVisible'] == 'none'
                    assert row['route'] == ''
                    assert 'no verified native route' in row['text']
                    assert page.locator('#nativeRouteScope').count() == 0
                else:
                    assert row['sourceDisabled'] is False
                    assert row['route']
                    assert 'Native route-scored DecisionRecord' in row['route']
                    assert row['routeVisible'] != 'none'

            # A source-only level change must request the backend's new record,
            # not merely relabel the old L10 record as L20.
            page.locator('#classPick').select_option('mage')
            page.locator('#levelPick').select_option('20')
            page.wait_for_function('''() => data?.selected_level===20 &&
                document.getElementById('backendPublication').innerText.includes('DecisionRecord L20')''', timeout=8000)
            result = page.evaluate('''() => ({
                level:state.level,selected:data.selected_level,
                calls:window.__g48Calls,
                text:document.getElementById('backendPublication').innerText,
                native:document.querySelector('#nativeRouteDecision')?.innerText||'',
            })''')
            assert result['level'] == result['selected'] == 20
            assert '/api/decisions?backend=generic&class=mage&level=20' in result['calls']
            assert 'DecisionRecord L20' in result['text']
            assert result['native'] == ''

            # A failed refresh restores the last published level instead of
            # mislabeling a retained L20 record as L11.
            page.evaluate('window.__g48Fail=true')
            page.locator('#levelPick').select_option('11')
            page.wait_for_function('''() => document.getElementById('backendPublication').innerText.includes('Decision loading failed')''', timeout=8000)
            assert page.locator('#levelPick').input_value() == '20'
            assert page.evaluate('state.level') == 20

            # Route classes still navigate local native scores, not the service.
            page.evaluate('''() => {data=window.__g48Response;state.cls='warrior';state.level=NaN;
                state.route='';state.target='';syncState();renderAll();window.__g48Fail=false;}''')
            before = len(page.evaluate('window.__g48Calls'))
            page.locator('#levelPick').select_option('11')
            assert len(page.evaluate('window.__g48Calls')) == before
            assert 'warrior L11 / target L12' in page.locator('#nativeRouteDecision').inner_text()
            assert not errors, errors
        finally:
            browser.close()


def test_generic_decision_service_timeout_covers_measured_cold_level(monkeypatch):
    from src.service.client import ServiceClient
    seen = []
    def fake_request(self, method, path, body=None, *, timeout=None):
        seen.append((method, path, timeout))
        return {}
    monkeypatch.setattr(ServiceClient, "_request", fake_request)
    client = ServiceClient("http://127.0.0.1:1", timeout=0.75)
    client.decisions(level=20, backend_id="generic")
    client.decisions(level=20, backend_id="legacy")
    assert seen[0] == ("GET", "/api/v1/decisions?backend=generic&level=20", 65.0)
    assert seen[1] == ("GET", "/api/v1/decisions?backend=legacy&level=20", 15.0)


def test_generic_l20_real_service_listener_http_refresh(monkeypatch, tmp_path):
    """A 38s cold source-only refresh must survive the *actual* proxy chain."""
    import json
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import urlopen

    from src import listener
    from src.service.client import ServiceClient
    from src.service.http_api import OptimizerHTTPServer
    from src.service.store import QueueStore

    servers, threads = [], []
    def start(server):
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        servers.append(server)
        threads.append(t)
        return f"http://127.0.0.1:{server.server_address[1]}"
    try:
        service = start(OptimizerHTTPServer(('127.0.0.1', 0), QueueStore(tmp_path/'jobs.sqlite3')))
        monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(service, timeout=0.75))
        proxy = start(ThreadingHTTPServer(('127.0.0.1', 0), listener.Handler))
        with urlopen(proxy + '/api/decisions?backend=generic&level=20', timeout=70) as response:
            payload = json.load(response)
        assert payload['selected_level'] == 20
        assert payload['active_backend'] == 'generic'
        assert {r['identity']['class_name'] for r in payload['decisions']} == set(registered_class_keys())
        assert all(r['identity']['level'] == 20 for r in payload['decisions'])
        assert len(payload['native_route_decisions']) == 26
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for t in threads:
            t.join(timeout=3)
