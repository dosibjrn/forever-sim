"""G46g: no implicit local heavyweight route computation on service outage."""
import pytest
from src.service.client import ServiceClientError
import src.listener as listener

class DownService:
    def decisions(self, **_):
        raise ServiceClientError('intentional test outage')

def test_fail_closed_without_local_recompute(monkeypatch):
    monkeypatch.delenv('WOW_LISTENER_OFFLINE_DECISIONS', raising=False)
    monkeypatch.setattr(listener,'_SERVICE_CLIENT',DownService())
    monkeypatch.setattr(listener,'build_decision_payload',lambda **_:pytest.fail('must not run local optimizer'))
    with pytest.raises(ServiceClientError,match='intentional test outage'):
        listener.decision_snapshot(10,'generic')

def test_explicit_offline_mode_allows_local_path(monkeypatch):
    monkeypatch.setenv('WOW_LISTENER_OFFLINE_DECISIONS','1')
    monkeypatch.setattr(listener,'_SERVICE_CLIENT',DownService())
    monkeypatch.setattr(listener,'build_decision_payload',lambda **_:{'offline':'explicit'})
    assert listener.decision_snapshot(10,'generic')=={'offline':'explicit'}

def test_http_listener_reports_service_outage_without_local_solve(monkeypatch):
    import json, threading
    from http.server import ThreadingHTTPServer
    from urllib.error import HTTPError
    from urllib.request import urlopen
    monkeypatch.delenv('WOW_LISTENER_OFFLINE_DECISIONS',raising=False)
    monkeypatch.setattr(listener,'_SERVICE_CLIENT',DownService())
    monkeypatch.setattr(listener,'build_decision_payload',lambda **_:pytest.fail('HTTP must not run local optimizer'))
    server=ThreadingHTTPServer(('127.0.0.1',0),listener.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with pytest.raises(HTTPError) as info:
            urlopen(f'http://127.0.0.1:{server.server_address[1]}/api/decisions?backend=generic&level=10',timeout=3)
        assert info.value.code==503
        result=json.loads(info.value.read())
        assert result['service_authority']=='unavailable'
        assert result['offline_fallback'] is False
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
