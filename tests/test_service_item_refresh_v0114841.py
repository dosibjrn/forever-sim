from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from src.rulesets.forever.items.catalogue import ItemCatalogue, ItemRecord, RequiredLevelOrigin
from src.service import http_api
from src.service.item_refresh import _preserve_verified_details


def test_preserve_verified_point_detail_and_eligibility(tmp_path: Path):
    old = tmp_path / 'old.sqlite'
    new = tmp_path / 'new.sqlite'
    with ItemCatalogue(old) as cat:
        cat.upsert_item(ItemRecord(
            item_id=250531, name="Acolyte's Silvered Chain Helm", slot='head',
            item_level=35, required_level=30,
            required_level_origin=RequiredLevelOrigin.OBSERVED.value,
            armor_type='mail', stamina=10, intellect=8,
            source_url='https://www.wowhead.com/forever/item=250531',
            identity_origin='wowhead_item', fetch_status='verified',
            last_verified_at='2026-09-29T12:00:00Z',
        ))
        cat.add_class_eligibility(250531, 2, 'point_add:test')
        cat.upsert_item(ItemRecord(item_id=1, name='stale list row', slot='head', fetch_status='verified_listview'))
    with ItemCatalogue(new) as cat:
        cat.upsert_item(ItemRecord(item_id=250531, name='list name', slot='head', item_level=35, fetch_status='verified_listview'))
        cat.upsert_item(ItemRecord(item_id=1, name='fresh list row', slot='head', fetch_status='verified_listview'))

    assert _preserve_verified_details(old, new) == 1
    with ItemCatalogue(new) as cat:
        item = cat.get_item(250531)
        assert item is not None
        assert item.name == "Acolyte's Silvered Chain Helm"
        assert item.fetch_status == 'verified'
        assert cat.get_item(1).name == 'fresh list row'
        rows = cat._conn.execute('SELECT class_id FROM item_class_eligibility WHERE item_id=250531').fetchall()
        assert [r[0] for r in rows] == [2]


def test_refresh_http_endpoint_is_async(monkeypatch, tmp_path: Path):
    fake = {'id':'abc123','state':'queued','classes':['mage','druid','paladin']}
    monkeypatch.setattr(http_api, 'start_refresh', lambda classes=None: dict(fake, classes=classes or fake['classes']))
    # Exercise the handler through a real ephemeral HTTP server helper pattern used by other tests.
    from http.server import ThreadingHTTPServer
    import threading, urllib.request
    from src.service.store import QueueStore

    db = tmp_path / 'queue.sqlite3'
    server = ThreadingHTTPServer(('127.0.0.1',0), http_api.OptimizerAPIHandler)
    server.store = QueueStore(db)
    server.verbose = False
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        req = urllib.request.Request(
            f'http://127.0.0.1:{server.server_address[1]}/api/v1/items/refresh',
            data=json.dumps({'classes':['mage','druid','paladin']}).encode(),
            headers={'Content-Type':'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=2) as r:
            body = json.loads(r.read())
            assert r.status == 202
        assert body['refresh']['state'] == 'queued'
        assert body['refresh']['classes'] == ['mage','druid','paladin']
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_listener_exposes_bulk_refresh_control():
    import src.listener as listener
    assert 'Refresh all items' in listener.DECISIONS_HTML
    assert '/api/service/items/refresh' in listener.DECISIONS_HTML
    assert "['mage','druid','paladin','hunter']" in listener.DECISIONS_HTML


def test_hunter_is_accepted_by_refresh_contract(monkeypatch):
    from src.service import item_refresh
    captured = {}
    class DummyThread:
        def __init__(self, *, target, args, name, daemon):
            captured["args"] = args
        def start(self):
            pass
    monkeypatch.setattr(item_refresh.threading, "Thread", DummyThread)
    monkeypatch.setattr(item_refresh, "_write_status", lambda task_id: None)
    item_refresh._TASKS.clear()
    task = item_refresh.start_refresh(["hunter"])
    assert task["classes"] == ["hunter"]
    assert captured["args"][1] == ["hunter"]
    item_refresh._TASKS.clear()
