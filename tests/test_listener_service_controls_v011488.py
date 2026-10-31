from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from src import listener


class FakeClient:
    base_url = "http://service.test"
    def __init__(self):
        self.jobs = {"abc": {"id": "abc", "state": "queued", "priority": 0, "request": {"class_name": "mage", "start_level": 11, "end_level": 40, "endpoint_mode": "smooth"}}}
    def health(self): return {"ok": True}
    def list_jobs(self): return list(self.jobs.values())
    def publications(self): return []
    def events(self, **_kwargs): return [{"seq": 7, "job_id": "abc", "kind": "enqueued", "payload": {}}]
    def enqueue(self, body):
        job = {"id": "new", "state": "queued", "priority": int(body.get("priority", 0)), "request": dict(body)}
        self.jobs["new"] = job
        return job, True
    def submit_intent(self, body):
        action=body.get("action","recompute_range"); level=int(body.get("level",body.get("from_level",11)))
        end=int(body.get("to_level",level)); depth=body.get("depth","standard")
        req={"ruleset":"forever","class_name":body.get("class_name","mage"),"start_level":level,"end_level":end,"endpoint_mode":"smooth","config":{"service_intent":{"action":action,"depth":depth}}}
        job={"id":"intent","state":"queued","priority":int(body.get("priority",0)),"request":req}
        self.jobs["intent"]=job
        return {"created":True,"job":job,"intent":{"action":action,"depth":depth},"summary":"intent accepted"}
    def add_item(self, item, *, class_name=None):
        return {"item_id":250531,"name":"Acolyte's Silvered Chain Helm","slot":"head","effective_required_level":20,"affected_from_level":20,"affected_to_level":60,"class_name":class_name}
    def control(self, job_id, action):
        if action == "checkpoint":
            self.jobs[job_id]["control_requested"] = "checkpoint"
            return dict(self.jobs[job_id])
        state = {"pause": "paused", "resume": "queued", "cancel": "cancelled"}[action]
        self.jobs[job_id]["state"] = state
        return dict(self.jobs[job_id])
    def reorder(self, job_ids):
        return [dict(self.jobs[j]) for j in job_ids]
    def clone(self, job_id, *, overrides=None, priority=None, deduplicate=False):
        req=dict(self.jobs[job_id]["request"]); req.update(overrides or {})
        job={"id":"clone","state":"queued","priority":int(priority or 0),"request":req}
        self.jobs["clone"]=job
        return job, True
    def set_priority(self, job_id, value):
        self.jobs[job_id]["priority"] = int(value)
        return dict(self.jobs[job_id])


def _post(server, path, body):
    raw = json.dumps(body).encode()
    req = Request(f"http://127.0.0.1:{server.server_port}{path}", data=raw, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=2) as resp:
        return resp.status, json.loads(resp.read().decode())


def test_decisions_ui_has_durable_queue_controls_and_no_optimizer_execution():
    html = listener.DECISIONS_HTML
    assert "Optimizer service" in html
    assert "Run request" in html
    assert "enqueueSelectedJob" in html
    assert "controlJob" in html
    assert "reorder_up" in html and "reorder_down" in html
    assert "checkpoint now" in html and "rerun/edit" in html
    assert "Pending:" in html and "Accepted:" in html and "Rejected:" in html
    assert "Published results · selected class" in html
    assert "latest_checkpoint" in html and "latest_attempt" in html
    assert "data-job-action=\"history\"" in html and "loadLineage" in html
    assert "A running or failed job does not replace the last good publication." in html
    assert "DB schema" in html
    assert "setInterval(loadServiceStatus,2000)" in html
    # Browser only talks to listener's service proxy; it never starts optimizer subprocesses.
    assert "const path='/api/service/intents'" in html
    assert "fetch(path,{method:'POST'" in html
    assert "src.v2.runner" not in html
    assert 'id="jobAction"' in html and 'id="jobDepth"' in html
    assert 'id="jobMode"' not in html
    assert '<option value="mc">' not in html
    assert 'id="addItemInput"' in html and 'addSelectedItem' in html
    assert "'/api/service/items/add'" in html
    assert '<a href="/fast">Fast</a>' not in html and '<a href="/">MC</a>' not in html


def test_listener_service_proxy_enqueues_and_controls_via_http_client(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(listener, "_SERVICE_CLIENT", fake)
    server = ThreadingHTTPServer(("127.0.0.1", 0), listener.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, result = _post(server, "/api/service/jobs", {"ruleset": "forever", "class_name": "mage", "start_level": 11, "end_level": 40, "endpoint_mode": "smooth", "priority": 2})
        assert status == 200 and result["created"] is True
        assert result["job"]["priority"] == 2
        status, result = _post(server, "/api/service/jobs/new/pause", {})
        assert status == 200 and result["state"] == "paused"
        status, result = _post(server, "/api/service/jobs/new/priority", {"priority": 5})
        assert status == 200 and result["priority"] == 5
        status, result = _post(server, "/api/service/jobs/new/resume", {})
        assert status == 200 and result["state"] == "queued"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_service_snapshot_carries_jobs_and_latest_events(monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(listener, "_SERVICE_CLIENT", fake)
    snap = listener.service_snapshot()
    assert snap["available"] is True
    assert snap["jobs"][0]["id"] == "abc"
    assert snap["latest_events"]["abc"]["kind"] == "enqueued"
    assert snap["event_cursor"] == 7


def test_listener_service_proxy_adds_item_for_selected_class(monkeypatch):
    fake=FakeClient(); monkeypatch.setattr(listener,"_SERVICE_CLIENT",fake)
    server=ThreadingHTTPServer(("127.0.0.1",0),listener.Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        status,result=_post(server,"/api/service/items/add",{"item":"250531","class_name":"paladin"})
        assert status==200 and result["item_id"]==250531 and result["class_name"]=="paladin"
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
