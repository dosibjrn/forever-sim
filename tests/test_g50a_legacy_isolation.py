"""G50a: real generic decision publication survives an explicit legacy cutout.

This intentionally does not pretend the incomplete generic product is ready to
be the automatic default; ineligible auto requests fail closed in cutout mode.
"""
from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from src.v2 import decision_dashboard as dashboard
from src.v2.backend_selection import select_backend


def _forbidden(*args, **kwargs):
    raise AssertionError('G50a generic path attempted to read legacy publication')


def test_cutout_rejects_legacy_compare_and_ineligible_auto_before_read(monkeypatch):
    monkeypatch.setenv('WOW_DISABLE_LEGACY_DECISIONS', '1')
    monkeypatch.setattr(dashboard, 'read_published_class_artifact', _forbidden)
    monkeypatch.setattr(dashboard, 'read_json', _forbidden)
    assert select_backend(class_key='druid', level=10)['backend'] == 'legacy'
    for backend in (None, 'legacy', 'compare'):
        with pytest.raises(dashboard.LegacyDecisionsDisabled):
            dashboard.build_decision_payload(selected_level=10, class_name='druid', backend_id=backend)
    assert dashboard.legacy_decisions_disabled()
    monkeypatch.delenv('WOW_DISABLE_LEGACY_DECISIONS')
    assert not dashboard.legacy_decisions_disabled()


def test_real_generic_payload_runs_with_legacy_artifacts_forbidden(monkeypatch):
    monkeypatch.setenv('WOW_DISABLE_LEGACY_DECISIONS', 'true')
    monkeypatch.setattr(dashboard, 'read_published_class_artifact', _forbidden)
    monkeypatch.setattr(dashboard, 'read_json', _forbidden)
    payload = dashboard.build_decision_payload(
        selected_level=10, class_name='druid', backend_id='generic',
    )
    assert payload['active_backend'] == 'generic'
    assert payload['backend_selection']['mode'] == 'explicit'
    assert payload['backend_selection']['legacy_fallback'] is False
    assert len(payload['decisions']) >= 5
    assert {row['identity']['class_name'].lower() for row in payload['decisions']} >= {'druid','mage','warrior'}
    assert payload['generic_routes']['legacy_fallback'] is False
    assert payload['native_route_decisions'], 'real generic route publication was not produced'


def test_legacy_cutout_is_http_503_at_both_hops_not_silent_generic(monkeypatch, tmp_path):
    from src import listener
    from src.service.client import ServiceClient
    from src.service.http_api import OptimizerHTTPServer
    from src.service.store import QueueStore

    monkeypatch.setenv('WOW_DISABLE_LEGACY_DECISIONS', 'yes')
    servers, threads = [], []

    def start(server):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        threads.append(thread)
        return f'http://127.0.0.1:{server.server_address[1]}'

    def get_json(url):
        try:
            with urlopen(url, timeout=22) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    try:
        service = start(OptimizerHTTPServer(('127.0.0.1', 0), QueueStore(tmp_path / 'q.sqlite3')))
        monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(service, timeout=20))
        proxy = start(ThreadingHTTPServer(('127.0.0.1', 0), listener.Handler))
        for suffix in ('?class=druid&level=10', '?backend=legacy&class=druid&level=10',
                       '?backend=compare&class=druid&level=10'):
            direct_status, direct = get_json(service + '/api/v1/decisions' + suffix)
            listener_status, forwarded = get_json(proxy + '/api/decisions' + suffix)
            assert direct_status == listener_status == 503
            assert direct.get('error') == 'legacy_decisions_disabled'
            assert direct['legacy_fallback'] is False
            assert forwarded.get('offline_fallback') is False
            assert 'decisions' not in forwarded  # cannot masquerade as an alternative backend
        direct_status, direct = get_json(service + '/api/v1/decisions?backend=generic&class=druid&level=10')
        listener_status, forwarded = get_json(proxy + '/api/decisions?backend=generic&class=druid&level=10')
        assert direct_status == listener_status == 200
        assert forwarded['active_backend'] == direct['active_backend'] == 'generic'
        assert forwarded['decisions'] == direct['decisions']
        assert forwarded['backend_selection']['legacy_fallback'] is False
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)
