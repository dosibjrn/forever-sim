from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

from src.service.executors import ExecutionPlan
from src.service.models import JobRequest
from src.service.publication import publication_chain, resolve_published_path
from src.service.scheduler import Scheduler
from src.service.store import QueueStore
import src.service.scheduler as scheduler_module


def req(cls: str, start: int, end: int, *, workers: int = 1) -> JobRequest:
    return JobRequest(
        ruleset="forever", class_name=cls, start_level=start, end_level=end,
        endpoint_mode="smooth", config={"workers": workers},
    )


def _script(exit_code: int = 0, delay: float = 0.08) -> str:
    return rf'''
import json, os, pathlib, sys, time
cls=sys.argv[1]
root=pathlib.Path(os.environ["WOW_SIM_STATE_BASE"])
viewer=root / "games" / f"forever-{{cls}}" / "v2" / "viewer.json"
viewer.parent.mkdir(parents=True,exist_ok=True)
viewer.write_text(json.dumps({{"running":False,"class":cls,"marker":f"v4-{{cls}}"}}))
cp=root / "runtime" / f"checkpoint-{{cls}}.json"
cp.parent.mkdir(parents=True,exist_ok=True)
cp.write_text(json.dumps({{"class":cls,"marker":f"cp-{{cls}}"}}))
time.sleep({delay})
sys.exit({exit_code})
'''


class DummyExecutor:
    def __init__(self, cls: str, *, exit_code: int = 0, delay: float = 0.08):
        self.cls=cls; self.exit_code=exit_code; self.delay=delay
    def plan(self, job):
        return ExecutionPlan(kind="v4_isolation_probe", command=[sys.executable, "-c", _script(self.exit_code, self.delay), self.cls])


def _assert_isolated(store: QueueStore, claimed):
    by_class={c.job["request"]["class_name"]: c for c in claimed}
    for cls,c in by_class.items():
        root=Path(c.attempt["run_root"])/"state"
        assert (root/f"games/forever-{cls}/v2/viewer.json").is_file()
        assert (root/f"runtime/checkpoint-{cls}.json").is_file()
        for other in by_class:
            if other == cls: continue
            assert not (root/f"games/forever-{other}/v2/viewer.json").exists()
            assert not (root/f"runtime/checkpoint-{other}.json").exists()
        cps=store.list_checkpoints(c.job["id"])
        assert cps and all(x["job_id"]==c.job["id"] and x["attempt_id"]==c.attempt["id"] for x in cps)
        assert all(str(Path(x["path"])).startswith(str(Path(c.attempt["run_root"]))) for x in cps)
        assert all(e["job_id"]==c.job["id"] for e in store.events(c.job["id"]))


def test_repeated_concurrent_jobs_are_deterministically_isolated(tmp_path: Path, monkeypatch):
    for round_no in range(3):
        project=tmp_path/f"round-{round_no}"; project.mkdir()
        store=QueueStore(project/"state/service/queue.sqlite3")
        jobs=[store.enqueue(req("mage",20,21),deduplicate=False)[0], store.enqueue(req("paladin",30,31),deduplicate=False)[0]]
        sched=Scheduler(store,runs_root=project/"state/runs",owner=f"v4-{round_no}",max_active_jobs=2,max_resource_units=2,lease_seconds=5)
        claimed=[sched.claim(),sched.claim()]
        assert all(claimed) and sched.claim() is None
        assert len({c.attempt["run_root"] for c in claimed})==2
        monkeypatch.setattr(scheduler_module,"executor_for",lambda job: DummyExecutor(job["request"]["class_name"]))
        with ThreadPoolExecutor(max_workers=2) as pool:
            out=list(pool.map(lambda c:sched.run_claimed(c,project_root=project,poll_seconds=0.01),claimed))
        assert {x["state"] for x in out}=={"completed"}
        _assert_isolated(store,claimed)
        chain=publication_chain(project)
        assert {p["job_id"] for p in chain[:2]}=={j["id"] for j in jobs}
        assert resolve_published_path(project,"games/forever-mage/v2/viewer.json").is_file()
        assert resolve_published_path(project,"games/forever-paladin/v2/viewer.json").is_file()
        assert not (project/"state/games").exists()


def test_resource_admission_skips_too_large_job_without_oversubscription(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    big1,_=store.enqueue(req("mage",20,20,workers=2),priority=30,deduplicate=False)
    big2,_=store.enqueue(req("paladin",20,20,workers=2),priority=20,deduplicate=False)
    small,_=store.enqueue(req("druid",20,20,workers=1),priority=10,deduplicate=False)
    sched=Scheduler(store,runs_root=tmp_path/"runs",owner="v4-admission",max_active_jobs=3,max_resource_units=3)
    a=sched.claim(); b=sched.claim()
    assert a.job["id"]==big1["id"] and b.job["id"]==small["id"]
    assert sched.claim() is None and store.get(big2["id"])["state"]=="queued"
    snap=store.status_snapshot()
    assert sum(int((j["request"].get("config") or {}).get("workers",1)) for j in snap["jobs"] if j["state"]=="running") <= 3


def test_one_failed_job_cannot_corrupt_other_publication(tmp_path: Path, monkeypatch):
    project=tmp_path/"project"; project.mkdir()
    store=QueueStore(project/"state/service/queue.sqlite3")
    mage,_=store.enqueue(req("mage",20,21),deduplicate=False)
    pal,_=store.enqueue(req("paladin",40,41),deduplicate=False)
    sched=Scheduler(store,runs_root=project/"state/runs",owner="v4-failure",max_active_jobs=2,max_resource_units=2,lease_seconds=5)
    claimed=[sched.claim(),sched.claim()]
    def factory(job):
        cls=job["request"]["class_name"]
        return DummyExecutor(cls,exit_code=7 if cls=="paladin" else 0,delay=0.10)
    monkeypatch.setattr(scheduler_module,"executor_for",factory)
    with ThreadPoolExecutor(max_workers=2) as pool:
        out=list(pool.map(lambda c:sched.run_claimed(c,project_root=project,poll_seconds=0.01),claimed))
    states={x["request"]["class_name"]:x["state"] for x in out}
    assert states=={"mage":"completed","paladin":"failed"}
    _assert_isolated(store,claimed)
    pubs=store.list_publications()
    assert [p["job_id"] for p in pubs]==[mage["id"]]
    assert resolve_published_path(project,"games/forever-mage/v2/viewer.json").is_file()
    assert not resolve_published_path(project,"games/forever-paladin/v2/viewer.json").exists()


def test_control_plane_reads_and_controls_two_running_jobs_independently(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    jobs=[store.enqueue(req("mage",20,22),deduplicate=False)[0],store.enqueue(req("druid",30,32),deduplicate=False)[0]]
    sched=Scheduler(store,runs_root=tmp_path/"runs",owner="v4-control",max_active_jobs=2,max_resource_units=2)
    claimed=[sched.claim(),sched.claim()]
    snap=store.status_snapshot()
    running={j["id"] for j in snap["jobs"] if j["state"]=="running"}
    assert running=={j["id"] for j in jobs}
    store.request_control(jobs[0]["id"],"pause")
    store.request_control(jobs[1]["id"],"cancel")
    assert store.requested_control(jobs[0]["id"])=="pause"
    assert store.requested_control(jobs[1]["id"])=="cancel"
    # Independent durable requests remain attached to their own job/attempt rows.
    snap=store.status_snapshot()
    by_id={j["id"]:j for j in snap["jobs"]}
    assert by_id[jobs[0]["id"]]["control_requested"]=="pause"
    assert by_id[jobs[1]["id"]]["control_requested"]=="cancel"
    assert by_id[jobs[0]["id"]]["latest_attempt"]["id"] != by_id[jobs[1]["id"]]["latest_attempt"]["id"]


def test_listener_proxy_reads_and_controls_both_concurrent_jobs(tmp_path: Path, monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import Request, urlopen
    from src import listener
    from src.service.client import ServiceClient
    from src.service.http_api import OptimizerHTTPServer

    store=QueueStore(tmp_path/"q.sqlite3")
    jobs=[store.enqueue(req("mage",20,22),deduplicate=False)[0],store.enqueue(req("paladin",30,32),deduplicate=False)[0]]
    sched=Scheduler(store,runs_root=tmp_path/"runs",owner="v4-listener",max_active_jobs=2,max_resource_units=2)
    assert sched.claim() and sched.claim()

    api=OptimizerHTTPServer(("127.0.0.1",0),store)
    api_t=threading.Thread(target=api.serve_forever,daemon=True); api_t.start()
    client=ServiceClient(f"http://127.0.0.1:{api.server_address[1]}",timeout=2)
    monkeypatch.setattr(listener,"_SERVICE_CLIENT",client)
    ui=ThreadingHTTPServer(("127.0.0.1",0),listener.Handler)
    ui_t=threading.Thread(target=ui.serve_forever,daemon=True); ui_t.start()
    try:
        snap=listener.service_snapshot()
        assert {j["id"] for j in snap["active_jobs"]}=={j["id"] for j in jobs}
        def post(path):
            r=Request(f"http://127.0.0.1:{ui.server_port}{path}",data=b"{}",method="POST",headers={"Content-Type":"application/json"})
            with urlopen(r,timeout=2) as resp:
                return json.loads(resp.read().decode())
        a=post(f"/api/service/jobs/{jobs[0]['id']}/pause")
        b=post(f"/api/service/jobs/{jobs[1]['id']}/cancel")
        assert a["control_requested"]=="pause"
        assert b["control_requested"]=="cancel"
        snap=listener.service_snapshot(); by_id={j["id"]:j for j in snap["jobs"]}
        assert by_id[jobs[0]["id"]]["control_requested"]=="pause"
        assert by_id[jobs[1]["id"]]["control_requested"]=="cancel"
    finally:
        ui.shutdown(); ui.server_close(); ui_t.join(timeout=2)
        api.shutdown(); api.server_close(); api_t.join(timeout=2)
