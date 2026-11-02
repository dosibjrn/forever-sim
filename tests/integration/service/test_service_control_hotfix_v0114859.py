from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from src import listener
from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore


def _post(server, path: str, body: dict):
    conn = HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
    conn.request('POST', path, body=json.dumps(body), headers={'Content-Type':'application/json'})
    res = conn.getresponse(); raw = res.read(); status = res.status; conn.close()
    return status, json.loads(raw.decode())


def test_paused_job_renders_resume_control():
    html = listener.DECISIONS_HTML
    assert "st==='paused'?['resume','cancel']" in html


def test_pause_before_first_attempt_can_resume_without_checkpoint(tmp_path: Path):
    store = QueueStore(tmp_path/'q.sqlite3')
    server = OptimizerHTTPServer(('127.0.0.1',0), store)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        client = ServiceClient(f"http://127.0.0.1:{server.server_address[1]}", timeout=1.0)
        job, created = client.enqueue({
            'ruleset':'forever','class_name':'druid','start_level':11,'end_level':20,'endpoint_mode':'fast'
        })
        assert created
        assert client.control(job['id'],'pause')['state'] == 'paused'
        assert client.control(job['id'],'resume')['state'] == 'queued'
        assert store.get(job['id'])['attempt_count'] == 0
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_add_item_uses_long_operation_timeout(monkeypatch):
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self):
            return json.dumps({'item_id':250531}).encode()

    def fake_urlopen(req, timeout):
        seen['timeout'] = timeout
        return Resp()

    import src.service.client as client_mod
    monkeypatch.setattr(client_mod, 'urlopen', fake_urlopen)
    c = ServiceClient('http://127.0.0.1:8765', timeout=2.0)
    assert c.add_item('250531', class_name='paladin')['item_id'] == 250531
    assert seen['timeout'] >= 60.0
