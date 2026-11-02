from __future__ import annotations

import importlib

import src.listener as listener
from src.service.client import ServiceClientError


class FlakyClient:
    base_url = "http://127.0.0.1:8765"
    def __init__(self):
        self.calls = 0
    def status(self):
        self.calls += 1
        if self.calls == 1:
            return {
                "api_version": 1,
                "schema_version": 1,
                "jobs": [{"id":"job1","state":"running","request":{"class_name":"druid"}}],
                "publications": [{"id":"pub1","created_at":1,"request":{"class_name":"druid"}}],
                "active_count": 1,
            }
        raise ServiceClientError("timed out")
    def item_refresh_status(self):
        return None


def _reset(monkeypatch):
    c=FlakyClient()
    monkeypatch.setattr(listener, "_SERVICE_CLIENT", c)
    monkeypatch.setattr(listener, "_SERVICE_LAST_GOOD", None)
    monkeypatch.setattr(listener, "_SERVICE_LAST_GOOD_AT", 0.0)
    monkeypatch.setattr(listener, "_SERVICE_CONSECUTIVE_FAILURES", 0)
    return c


def test_transient_timeouts_keep_last_good_snapshot(monkeypatch):
    _reset(monkeypatch)
    first=listener.service_snapshot()
    assert first["available"] is True
    assert first["jobs"][0]["id"] == "job1"
    for n in range(1,4):
        snap=listener.service_snapshot()
        assert snap["available"] is True
        assert snap["degraded"] is True
        assert snap["stale"] is True
        assert snap["consecutive_failures"] == n
        assert snap["jobs"][0]["id"] == "job1"
        assert snap["latest_publication"]["id"] == "pub1"


def test_sustained_outage_reports_offline_but_keeps_lkg(monkeypatch):
    _reset(monkeypatch)
    listener.service_snapshot()
    for _ in range(listener._SERVICE_STALE_GRACE_FAILURES):
        assert listener.service_snapshot()["available"] is True
    snap=listener.service_snapshot()
    assert snap["available"] is False
    assert snap["stale"] is True
    assert snap["jobs"][0]["id"] == "job1"
    assert snap["latest_publication"]["id"] == "pub1"


def test_listener_js_serializes_poll_and_preserves_stale_rows():
    html=listener.DECISIONS_HTML
    assert "if(servicePollInFlight)return" in html
    assert "finally{servicePollInFlight=false}" in html
    assert "Service offline · showing last known state" in html
    assert "renderPublications({publications:[]})" not in html
