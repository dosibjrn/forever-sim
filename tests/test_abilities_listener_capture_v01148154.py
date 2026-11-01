"""Source capture is an operator action with a durable, fail-closed catalogue."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src.service import abilities_refresh as ar
from src.service import http_api, item_refresh
from src.service.store import QueueStore
from tools.capture_forever_abilities_sqlite import capture_details


def test_uploaded_capture_is_full_source_index_without_invented_tooltips():
    stat = ar.catalogue_status()
    assert stat['index_complete'] is True
    assert stat['lists'] == 18
    assert stat['rows'] == 2724
    assert stat['details_verified'] == 0
    assert stat['unique_spells'] == 2663
    assert stat['engine_modeled'] is False
    assert all(x['captured_count'] == x['expected_count'] for x in stat['per_class'])


def test_staging_coverage_rejects_partial_capture(tmp_path: Path):
    from shutil import copyfile
    stage = tmp_path / 'stage.sqlite'
    copyfile(ar.CATALOGUE, stage)
    batch = ar.catalogue_status()['batch_id']
    good = ar._check_staging(stage, batch, 'index', previous_details=0)
    assert good['rows'] == 2724
    with sqlite3.connect(stage) as db:
        db.execute('DELETE FROM capture_lists WHERE batch_id=? AND class_key=? AND kind=?',
                   (batch, 'rogue', 'talents'))  # sqlite foreign_keys is not enabled here
        db.commit()
    with pytest.raises(ValueError, match='incomplete class list coverage'):
        ar._check_staging(stage, batch, 'index', previous_details=0)


def test_browser_job_publishes_only_verified_capture_and_retains_old_on_failure(tmp_path, monkeypatch):
    from shutil import copyfile
    cat = tmp_path / 'catalogue' / 'forever_abilities.sqlite'
    cat.parent.mkdir()
    copyfile(ar.CATALOGUE, cat)
    state = tmp_path / 'state'
    monkeypatch.setattr(ar, 'CATALOGUE', cat)
    monkeypatch.setattr(ar, 'STATE_DIR', state)
    prev = ar.catalogue_status(cat)

    class FakeCompleted:
        returncode = 0

    def fake_capture(command, **kwargs):
        new_batch = command[command.index('--batch-id') + 1]
        db_path = Path(command[command.index('--db') + 1])
        with sqlite3.connect(db_path) as db:
            old_batch = prev['batch_id']
            db.execute('INSERT INTO capture_batches VALUES (?,?,?,?,?,?)',
                       (new_batch, '2099-01-01T00:00:00Z', 'https://wowhead', None, 'complete', None))
            db.execute('INSERT INTO capture_lists SELECT ?,class_key,kind,source_url,expected_count,captured_count,complete,blocked_reason,content_sha256 FROM capture_lists WHERE batch_id=?',
                       (new_batch, old_batch))
            db.execute('INSERT INTO spell_index SELECT ?,class_key,kind,spell_id,name,rank_hint,level_hint,source_url,raw_listview_json FROM spell_index WHERE batch_id=?',
                       (new_batch, old_batch))
            db.commit()
        (db_path.parent / f'wowhead_abilities_manifest_{new_batch}.json').write_text(
            json.dumps({'batch_id':new_batch, 'index_complete': True}), encoding='utf-8')
        return FakeCompleted()

    monkeypatch.setattr(ar.subprocess, 'run', fake_capture)
    task_id = 'capture_success'
    ar._TASKS[task_id] = {'id':task_id,'state':'queued','created_at':1}
    ar._run(task_id, 'index', None)
    assert ar._TASKS[task_id]['state'] == 'completed'
    assert ar.catalogue_status(cat)['batch_id'] == ar._TASKS[task_id]['batch_id']
    assert ar.catalogue_status(cat)['rows'] == prev['rows']
    assert list(cat.parent.glob('wowhead_abilities_manifest_*.json'))

    def fake_failed_capture(command, **kwargs):
        class Fail:
            returncode = 2
        return Fail()

    before = cat.read_bytes()
    monkeypatch.setattr(ar.subprocess, 'run', fake_failed_capture)
    fail_id = 'capture_failure'
    ar._TASKS[fail_id] = {'id':fail_id,'state':'queued','created_at':2}
    ar._run(fail_id, 'index', None)
    assert ar._TASKS[fail_id]['state'] == 'failed'
    assert cat.read_bytes() == before
    assert not (state / (fail_id + '.sqlite')).exists()
    ar._TASKS.pop(task_id)
    ar._TASKS.pop(fail_id)


def test_detail_budget_advances_on_resume(tmp_path: Path):
    db = sqlite3.connect(tmp_path / 'catalogue.sqlite')
    from tools.capture_forever_abilities_sqlite import initialize_db
    initialize_db(db)
    db.execute('INSERT INTO capture_batches VALUES (?,?,?,?,?,?)', ('x','2026-10-08Z','wowhead',None,'complete',None))
    db.execute('INSERT INTO capture_lists VALUES (?,?,?,?,?,?,?,?,?)', ('x','rogue','abilities','wowhead',5,5,1,None,'foo'))
    for sid in [100,101,102,103,104]:
        db.execute('INSERT INTO spell_index VALUES (?,?,?,?,?,?,?,?,?)', ('x','rogue','abilities',sid,f'Rank{sid}',1,10,f'https://www.wowhead.com/forever/spell={sid}','{}'))
    db.commit()

    class Page:
        def goto(self, url, **kwargs):
            self.url = url
            return type('Response', (), {'status': 200})()
        def wait_for_timeout(self, n): pass
        def title(self): return f'Rank{self.url.split("=")[-1]} - Wowhead'
        def locator(self, s):
            return type('Body', (), {'inner_text': lambda _self, **kw: f'Rank{self.url.split("=")[-1]} details'})()
        def content(self): return f'<html><body><h1>Rank{self.url.split("=")[-1]}</h1><p>Spell details</p></body></html>'

    page = Page()
    assert capture_details(page, batch_id='x', db=db, timeout_ms=1000, settle_ms=0, max_details=2)['captured'] == 2
    assert capture_details(page, batch_id='x', db=db, timeout_ms=1000, settle_ms=0, max_details=2)['captured'] == 2
    ids = [i[0] for i in db.execute('SELECT spell_id FROM spell_details ORDER BY spell_id')]
    assert ids == [100,101,102,103]
    db.close()


def test_capture_admission_blocks_conflicting_chrome_profiles(tmp_path, monkeypatch):
    item_refresh._TASKS['busy'] = {'id':'busy','state':'capturing'}
    with pytest.raises(RuntimeError, match='item Wowhead capture already active'):
        ar.start_refresh('index')
    item_refresh._TASKS.clear()
    ar._TASKS['busy'] = {'id':'busy','state':'capturing'}
    monkeypatch.setattr(item_refresh, '_write_status', lambda task_id: None)
    with pytest.raises(RuntimeError, match='ability/talent Wowhead capture already active'):
        item_refresh.start_refresh(['mage'])
    ar._TASKS.clear()


def test_api_status_and_async_start_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(http_api, 'abilities_catalogue_status', lambda: {'index_complete':True,'rows':2724})
    monkeypatch.setattr(http_api, 'latest_abilities_refresh', lambda: {'state':'completed','id':'previous'})
    monkeypatch.setattr(http_api, 'start_abilities_refresh', lambda **kw: {'state':'queued','mode':kw['mode'], 'max_details':kw['max_details']})
    server = http_api.OptimizerHTTPServer(('127.0.0.1',0), QueueStore(tmp_path/'queue.db'))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    root = f'http://127.0.0.1:{server.server_address[1]}/api/v1/abilities/refresh'
    try:
        with urlopen(root, timeout=2) as r:
            v=json.load(r)
        assert v['catalogue']['rows'] == 2724 and v['refresh']['state'] == 'completed'
        body = json.dumps({'mode':'details','max_details':20}).encode()
        with urlopen(Request(root,data=body,headers={'Content-Type':'application/json'},method='POST'),timeout=2) as r:
            result=json.load(r)
            assert r.status == 202
        assert result['refresh'] == {'state':'queued','mode':'details','max_details':20}
        try:
            urlopen(Request(root,data=b'{"mode":"details","shell_command":"rm"}',headers={'Content-Type':'application/json'},method='POST'),timeout=2)
        except HTTPError as err:
            assert err.code == 400
        else:
            pytest.fail('unknown options accepted')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_listener_displays_and_proxies_capture_without_legacy_fallback():
    import src.listener as listener
    html=listener.DECISIONS_HTML
    for token in ('refreshAbilitiesButton','fetchAbilityDetailsButton','abilitiesCatalogueStatus',
                  'renderAbilityCapture','/api/service/abilities/refresh','Index ≠ full talent tree'):
        assert token in html
    assert "_SERVICE_CLIENT.refresh_abilities" in Path(listener.__file__).read_text()
    assert "'abilities_capture'" in Path(listener.__file__).read_text()


def test_listener_to_service_http_proxy_round_trip(tmp_path, monkeypatch):
    """Browser POST -> listener -> service (no listener-owned background thread)."""
    import src.listener as listener
    from src.service.client import ServiceClient
    monkeypatch.setattr(http_api, 'abilities_catalogue_status',
                        lambda: {'index_complete':True,'rows':2724,'lists':18,
                                 'details_verified':0,'unique_spells':2663})
    monkeypatch.setattr(http_api, 'latest_abilities_refresh', lambda: None)
    monkeypatch.setattr(http_api, 'start_abilities_refresh',
                        lambda **kw: {'id':'proof123','state':'queued','mode':kw['mode']})
    service = http_api.OptimizerHTTPServer(('127.0.0.1',0), QueueStore(tmp_path/'queue2.db'))
    service_thread = threading.Thread(target=service.serve_forever,daemon=True)
    service_thread.start()
    monkeypatch.setattr(listener, '_SERVICE_CLIENT', ServiceClient(
        base_url=f'http://127.0.0.1:{service.server_address[1]}',timeout=2.0))
    web_server = ThreadingHTTPServer(('127.0.0.1',0), listener.Handler)
    web_thread = threading.Thread(target=web_server.serve_forever,daemon=True)
    web_thread.start()
    root=f'http://127.0.0.1:{web_server.server_address[1]}'
    try:
        with urlopen(root+'/api/service',timeout=5) as resp:
            snapshot=json.load(resp)
        assert snapshot['available'] is True
        assert snapshot['abilities_capture']['catalogue']['rows'] == 2724
        req = Request(root+'/api/service/abilities/refresh',
            data=json.dumps({'mode':'index'}).encode(),method='POST',
            headers={'Content-Type':'application/json'})
        with urlopen(req,timeout=5) as resp:
            result=json.load(resp)
        assert result['refresh']['id']=='proof123'
        assert result['refresh']['state']=='queued'
    finally:
        web_server.shutdown();web_server.server_close();web_thread.join(timeout=2)
        service.shutdown();service.server_close();service_thread.join(timeout=2)
