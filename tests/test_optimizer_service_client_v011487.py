from __future__ import annotations

import threading
from pathlib import Path

from src.service.client import ServiceClient
from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore


def _server(tmp_path: Path):
    store = QueueStore(tmp_path / "q.sqlite3")
    server = OptimizerHTTPServer(("127.0.0.1", 0), store)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    host, port = server.server_address
    return store, server, thread, ServiceClient(f"http://{host}:{port}", timeout=1.0)


def test_shared_http_client_roundtrip_queue_control_and_reads(tmp_path: Path):
    store, server, thread, client = _server(tmp_path)
    try:
        assert client.health()["ok"] is True
        assert client.status()["ok"] is True
        job, created = client.enqueue({
            "ruleset": "forever", "class_name": "mage", "start_level": 11, "end_level": 20,
            "endpoint_mode": "fast", "priority": 3,
        })
        assert created is True
        assert client.get_job(job["id"])["priority"] == 3
        assert client.list_jobs()[0]["id"] == job["id"]
        assert client.set_priority(job["id"], 9)["priority"] == 9
        assert client.control(job["id"], "pause")["state"] == "paused"
        assert client.control(job["id"], "resume")["state"] == "queued"
        assert client.attempts(job["id"]) == []
        assert client.checkpoints(job["id"]) == []
        assert isinstance(client.publications(), list)
        assert any(e["job_id"] == job["id"] for e in client.events(job_id=job["id"]))
        # Authority check: mutations came through the HTTP server's QueueStore.
        assert store.get(job["id"])["priority"] == 9
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=1)


def test_listener_service_snapshot_is_http_client_only(monkeypatch):
    import src.listener as listener

    class FakeClient:
        base_url = "http://service.test"
        def health(self): return {"ok": True}
        def list_jobs(self):
            return [
                {"id": "run", "state": "running"},
                {"id": "done", "state": "completed"},
                {"id": "queue", "state": "queued"},
            ]
        def publications(self): return [{"id": "pub-new"}]

    monkeypatch.setattr(listener, "_SERVICE_CLIENT", FakeClient())
    snap = listener.service_snapshot()
    assert snap["available"] is True
    assert snap["active_count"] == 2
    assert [j["id"] for j in snap["active_jobs"]] == ["run", "queue"]
    assert snap["latest_publication"]["id"] == "pub-new"
