from http.client import HTTPConnection
from pathlib import Path
import json
import threading

from src.service.http_api import OptimizerHTTPServer
from src.service.store import QueueStore


def _server(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    srv=OptimizerHTTPServer(("127.0.0.1",0),store)
    t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
    return srv,t,store


def _req(srv, method, path, body=None, headers=None):
    conn=HTTPConnection("127.0.0.1",srv.server_address[1],timeout=3)
    raw=None if body is None else json.dumps(body)
    hdr={"Content-Type":"application/json"}; hdr.update(headers or {})
    conn.request(method,path,body=raw,headers=hdr)
    res=conn.getresponse(); data=res.read(); status=res.status; content_type=res.getheader("Content-Type")
    conn.close(); return status,content_type,data


def test_http_enqueue_read_and_controls_share_durable_store(tmp_path: Path):
    srv,t,store=_server(tmp_path)
    try:
        status,_,data=_req(srv,"POST","/api/v1/jobs",{
            "ruleset":"forever","class_name":"mage","start_level":11,"end_level":40,
            "endpoint_mode":"fast","priority":3,
        })
        assert status==201
        created=json.loads(data); jid=created["job"]["id"]
        assert store.get(jid)["priority"]==3

        status,_,data=_req(srv,"GET",f"/api/v1/jobs/{jid}")
        assert status==200 and json.loads(data)["request"]["end_level"]==40
        status,_,data=_req(srv,"POST",f"/api/v1/jobs/{jid}/pause",{})
        assert status==200 and json.loads(data)["state"]=="paused"
        status,_,data=_req(srv,"POST",f"/api/v1/jobs/{jid}/resume",{})
        assert status==200 and json.loads(data)["state"]=="queued"
        status,_,data=_req(srv,"POST",f"/api/v1/jobs/{jid}/priority",{"priority":9})
        assert status==200 and json.loads(data)["priority"]==9
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=2)


def test_http_event_cursor_and_sse_replay(tmp_path: Path):
    srv,t,store=_server(tmp_path)
    try:
        _,_,data=_req(srv,"POST","/api/v1/jobs",{
            "ruleset":"forever","class_name":"mage","start_level":11,"end_level":20,
        })
        jid=json.loads(data)["job"]["id"]
        store.record_event(jid,"probe",{"value":7})
        rows=store.events(jid); first_seq=rows[0]["seq"]

        status,_,data=_req(srv,"GET",f"/api/v1/events?after={first_seq}&limit=10")
        payload=json.loads(data)
        assert status==200
        assert [e["kind"] for e in payload["events"]]==["probe"]

        status,ctype,data=_req(srv,"GET",f"/api/v1/events/stream?after={first_seq}&follow=0")
        text=data.decode()
        assert status==200 and ctype.startswith("text/event-stream")
        assert "event: probe" in text and '"value":7' in text
        assert f"id: {rows[-1]['seq']}" in text
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=2)


def test_http_bad_requests_are_bounded_and_do_not_launch_work(tmp_path: Path):
    srv,t,store=_server(tmp_path)
    try:
        status,_,data=_req(srv,"POST","/api/v1/jobs",{"ruleset":"forever"})
        assert status==400 and b"missing required fields" in data
        assert store.list_jobs()==[]
        status,_,_= _req(srv,"GET","/api/v1/jobs/not-a-job")
        assert status==404
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=2)


def test_http_status_is_bounded_joined_read_model(tmp_path: Path):
    srv,t,store=_server(tmp_path)
    try:
        _,_,data=_req(srv,"POST","/api/v1/jobs",{
            "ruleset":"forever","class_name":"mage","start_level":11,"end_level":20,
            "endpoint_mode":"fast",
        })
        job=json.loads(data)["job"]
        claimed=store.claim_next(owner="test",runs_root=tmp_path/"runs",lease_seconds=30)
        assert claimed is not None
        job,attempt=claimed
        cp_path=Path(attempt["run_root"])/"state"/"checkpoint.json"
        cp_path.parent.mkdir(parents=True,exist_ok=True); cp_path.write_text("{}")
        store.record_checkpoint({
            "job_id":job["id"],"attempt_id":attempt["id"],"path":str(cp_path),"kind":"resume",
            "sha256":"abc","size_bytes":2,"request":job["request"],"created_at":attempt["started_at"],
        })
        store.record_publication({
            "id":"pub1","job_id":job["id"],"attempt_id":attempt["id"],"state_root":str(Path(attempt["run_root"])/"state"),
            "parent_id":None,"request":job["request"],"created_at":attempt["started_at"],
        })
        store.record_event(job["id"],"probe_progress",{"level":17,"phase":"smooth"})
        status,_,data=_req(srv,"GET","/api/v1/status")
        snap=json.loads(data)
        assert status==200 and snap["ok"] is True and snap["api_version"]==1
        assert snap["schema_version"]>=4 and snap["active_count"]==1
        row=snap["jobs"][0]
        assert row["id"]==job["id"]
        assert row["latest_event"]["kind"]=="probe_progress"
        assert row["latest_event"]["payload"]["level"]==17
        assert row["latest_checkpoint"]["kind"]=="resume"
        assert row["latest_attempt"]["id"]==attempt["id"]
        assert snap["publications"][0]["id"]=="pub1"
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=2)
