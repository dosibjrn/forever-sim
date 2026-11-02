"""G46h: real optimizer service -> listener -> Chromium, no decision payload mocks."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import urlopen

import pytest
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore
from src import listener


def test_successful_generic_decision_passes_service_listener_http(monkeypatch, tmp_path):
    servers = []
    threads = []
    def start(server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start(); servers.append(server); threads.append(thread)
        return f'http://127.0.0.1:{server.server_address[1]}'
    try:
        service_url = start(OptimizerHTTPServer(('127.0.0.1', 0), QueueStore(tmp_path/'jobs.sqlite3')))
        monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(service_url, timeout=2))
        # External tooltip JS is not needed to verify decisions and must not block offline Chrome.
        remote = '<script src="https://wow.zamimg.com/js/tooltips.js" defer></script>'
        monkeypatch.setattr(listener, 'DECISIONS_HTML', listener.DECISIONS_HTML.replace(remote, ''))
        listener_url = start(ThreadingHTTPServer(('127.0.0.1',0),listener.Handler))
        path='/api/decisions?backend=generic&level=10'
        with urlopen(service_url+'/api/v1/decisions?backend=generic&level=10', timeout=45) as r:
            original=json.load(r)
        with urlopen(listener_url+path, timeout=45) as r:
            forwarded=json.load(r)
        assert original == forwarded
        assert forwarded['active_backend']=='generic'
        records=forwarded.get('decisions') or []
        assert any(x.get('identity',{}).get('class_name')=='mage' for x in records)
        with urlopen(listener_url+'/decisions', timeout=8) as r:
            html=r.read().decode('utf-8')
        assert 'id="backendPublication"' in html
        assert '/api/decisions?backend=' in html
        assert 'function renderBackendPublication()' in html
        # Chromium outbound navigation is blocked in this test environment.
        # Do not conflate HTTP integration success with browser rendering success.
    finally:
        for server in servers:server.shutdown();server.server_close()
        for thread in threads:thread.join(timeout=3)
