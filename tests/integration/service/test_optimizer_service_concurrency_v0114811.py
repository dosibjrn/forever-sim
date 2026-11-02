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


def req(cls: str, *, workers: int = 1) -> JobRequest:
    return JobRequest(
        ruleset="forever", class_name=cls, start_level=20, end_level=20,
        endpoint_mode="smooth", config={"workers": workers},
    )


def test_admission_is_bounded_by_job_slots_and_resource_units(tmp_path: Path):
    store = QueueStore(tmp_path / "q.sqlite3")
    big1, _ = store.enqueue(req("mage", workers=2), priority=20, deduplicate=False)
    big2, _ = store.enqueue(req("paladin", workers=2), priority=10, deduplicate=False)
    small, _ = store.enqueue(req("druid", workers=1), priority=0, deduplicate=False)
    sched = Scheduler(
        store, runs_root=tmp_path / "runs", owner="p5",
        max_active_jobs=3, max_resource_units=3,
    )

    a = sched.claim(); assert a and a.job["id"] == big1["id"]
    # big2 no longer fits (2+2>3), so admission uses the otherwise-idle unit.
    b = sched.claim(); assert b and b.job["id"] == small["id"]
    assert sched.claim() is None
    assert store.get(big2["id"])["state"] == "queued"

    store.finish_attempt(a.attempt["id"], owner="p5", outcome="cancelled")
    c = sched.claim(); assert c and c.job["id"] == big2["id"]


def test_two_simultaneous_jobs_keep_writers_in_attempt_roots_and_publish_both(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"; project.mkdir()
    store = QueueStore(project / "state" / "service" / "queue.sqlite3")
    mage, _ = store.enqueue(req("mage"), deduplicate=False)
    pal, _ = store.enqueue(req("paladin"), deduplicate=False)
    sched = Scheduler(
        store, runs_root=project / "state" / "runs", owner="p5-daemon",
        lease_seconds=10, max_active_jobs=2, max_resource_units=2,
    )
    first = sched.claim(); second = sched.claim()
    assert first and second and first.job["id"] != second.job["id"]
    assert sched.claim() is None

    script = r'''
import json, os, pathlib, sys, time
cls=sys.argv[1]
root=pathlib.Path(os.environ["WOW_SIM_STATE_BASE"])
viewer=root / "games" / f"forever-{cls}" / "v2" / "viewer.json"
viewer.parent.mkdir(parents=True,exist_ok=True)
viewer.write_text(json.dumps({"running":False,"class":cls,"marker":f"only-{cls}"}))
time.sleep(0.20)
'''

    class DummyExecutor:
        def __init__(self, cls): self.cls=cls
        def plan(self, job):
            return ExecutionPlan(kind="p5_isolation_probe", command=[sys.executable, "-c", script, self.cls])

    monkeypatch.setattr(scheduler_module, "executor_for", lambda job: DummyExecutor(job["request"]["class_name"]))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda c: sched.run_claimed(c, project_root=project, poll_seconds=0.01), [first, second]))
    assert {r["state"] for r in results} == {"completed"}

    by_class = {c.job["request"]["class_name"]: c for c in (first, second)}
    mage_root = Path(by_class["mage"].attempt["run_root"]) / "state"
    pal_root = Path(by_class["paladin"].attempt["run_root"]) / "state"
    assert mage_root != pal_root
    assert (mage_root / "games/forever-mage/v2/viewer.json").is_file()
    assert not (mage_root / "games/forever-paladin/v2/viewer.json").exists()
    assert (pal_root / "games/forever-paladin/v2/viewer.json").is_file()
    assert not (pal_root / "games/forever-mage/v2/viewer.json").exists()

    # Canonical publication is an overlay over immutable roots: both simultaneous
    # completions remain reachable, and neither optimizer wrote canonical game state.
    assert json.loads(resolve_published_path(project, "games/forever-mage/v2/viewer.json").read_text())["marker"] == "only-mage"
    assert json.loads(resolve_published_path(project, "games/forever-paladin/v2/viewer.json").read_text())["marker"] == "only-paladin"
    chain = publication_chain(project)
    assert {p["job_id"] for p in chain[:2]} == {mage["id"], pal["id"]}
    assert not (project / "state" / "games").exists()
