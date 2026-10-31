from __future__ import annotations

import json
import threading
from pathlib import Path

from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.models import JobRequest
from src.service.publication import publish_attempt
from src.service.store import QueueStore
import src.listener as listener


def _published_druid(project: Path, marker: str) -> QueueStore:
    store=QueueStore(project/'state/service/queue.sqlite3')
    req=JobRequest(ruleset='forever', class_name='druid', start_level=20, end_level=20, endpoint_mode='fast')
    job,_=store.enqueue(req,deduplicate=False)
    claimed=store.claim_next(owner='test',runs_root=project/'runs',lease_seconds=60)
    assert claimed is not None
    job,attempt=claimed
    state=Path(attempt['run_root'])/'state'
    viewer=state/'games/forever-druid/v2/viewer.json'
    viewer.parent.mkdir(parents=True,exist_ok=True)
    viewer.write_text(json.dumps({'running':False,'views':{},'marker':marker}),encoding='utf-8')
    ep=state/'decisions/forever/endpoint_paths.json'
    ep.parent.mkdir(parents=True,exist_ok=True)
    ep.write_text(json.dumps({'schema_version':1,'classes':{'druid':{'marker':marker}}}),encoding='utf-8')
    pub=publish_attempt(project,job=job,attempt=attempt)
    store.record_publication(pub)
    return store


def test_service_decisions_endpoint_uses_service_project_root(tmp_path: Path):
    service_root=tmp_path/'service-repo'; service_root.mkdir()
    store=_published_druid(service_root,'SERVICE-AUTHORITY')
    server=OptimizerHTTPServer(('127.0.0.1',0),store,project_root=service_root)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        client=ServiceClient(f'http://127.0.0.1:{server.server_address[1]}',timeout=2)
        payload=client.decisions()
        assert payload['endpoint_paths']['druid']['marker']=='SERVICE-AUTHORITY'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_listener_decisions_follow_service_not_listener_local_state(tmp_path: Path, monkeypatch):
    service_root=tmp_path/'service-repo'; service_root.mkdir()
    store=_published_druid(service_root,'REMOTE-PUBLISHED')
    server=OptimizerHTTPServer(('127.0.0.1',0),store,project_root=service_root)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        client=ServiceClient(f'http://127.0.0.1:{server.server_address[1]}',timeout=2)
        monkeypatch.setattr(listener,'_SERVICE_CLIENT',client)
        monkeypatch.setattr(listener,'build_decision_payload',lambda **kwargs:{'endpoint_paths':{'druid':{'marker':'WRONG-LOCAL'}}})
        payload=listener.decision_snapshot()
        assert payload['endpoint_paths']['druid']['marker']=='REMOTE-PUBLISHED'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
