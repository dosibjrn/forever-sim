from pathlib import Path
import json

from src.game_context import STATE_BASE_ENV
from src.service.models import JobRequest
from src.service.scheduler import Scheduler
from src.service.store import QueueStore


def req(cls="mage", start=11, end=20):
    return JobRequest(ruleset="forever", class_name=cls, start_level=start, end_level=end)


def test_claim_is_single_owner_and_creates_immutable_attempt_root(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    first,_=store.enqueue(req("mage"),priority=0)
    second,_=store.enqueue(req("paladin",10,20),priority=10)
    s=Scheduler(store,runs_root=tmp_path/"runs",owner="daemon-a",lease_seconds=10)
    claimed=s.claim()
    assert claimed is not None
    assert claimed.job["id"] == second["id"]
    assert Path(claimed.attempt["run_root"]).is_dir()
    assert store.get(second["id"])["state"] == "running"
    assert s.claim() is None
    assert store.get(first["id"])["state"] == "queued"


def test_expired_lease_requeues_and_new_attempt_gets_new_root(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    job,_=store.enqueue(req())
    a=store.claim_next(owner="dead",runs_root=tmp_path/"runs",lease_seconds=1,now=100.0)
    assert a is not None
    first_attempt=a[1]
    b=store.claim_next(owner="new",runs_root=tmp_path/"runs",lease_seconds=10,now=102.0)
    assert b is not None
    assert b[0]["id"] == job["id"]
    assert b[1]["id"] != first_attempt["id"]
    assert b[1]["run_root"] != first_attempt["run_root"]
    assert store.get_attempt(first_attempt["id"])["state"] == "expired"


def test_running_pause_is_request_until_scheduler_safe_boundary(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    job,_=store.enqueue(req())
    claimed=store.claim_next(owner="d",runs_root=tmp_path/"runs")
    assert claimed is not None
    pending=store.request_control(job["id"],"pause")
    assert pending["state"] == "running"
    assert pending["control_requested"] == "pause"
    done=store.finish_attempt(claimed[1]["id"],owner="d",outcome="paused")
    assert done["state"] == "paused"
    assert done["current_attempt_id"] is None


def test_state_base_override_isolation(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(STATE_BASE_ENV,str(tmp_path/"attempt-state"))
    # Import after env selection: the helper itself is the contract needed by workers.
    from src import game_context
    game_context.configure("forever","mage")
    root=game_context.v2_state_root(Path("/irrelevant/project"))
    assert root == tmp_path/"attempt-state"/"games"/"forever-mage"/"v2"


def test_expired_owner_preserves_durable_control_intent(tmp_path: Path):
    # Pending checkpoint must survive crash/reclaim; pause/cancel are satisfied
    # once the dead owner is fenced, rather than silently restarting fresh work.
    store=QueueStore(tmp_path/'q.sqlite3')
    job,_=store.enqueue(req())
    claimed=store.claim_next(owner='dead',runs_root=tmp_path/'runs',lease_seconds=1,now=10.0)
    assert claimed is not None
    store.request_control(job['id'],'checkpoint')
    replacement=store.claim_next(owner='new',runs_root=tmp_path/'runs',lease_seconds=10,now=12.0)
    assert replacement is not None
    assert store.get(job['id'])['control_requested']=='checkpoint'

    for action, expected in [('pause','paused'),('cancel','cancelled')]:
        sx=QueueStore(tmp_path/f'{action}.sqlite3')
        j,_=sx.enqueue(req('mage',21,21))
        a=sx.claim_next(owner='dead',runs_root=tmp_path/f'runs-{action}',lease_seconds=1,now=20.0)
        assert a is not None
        sx.request_control(j['id'],action)
        sx.recover_expired(now=22.0)
        assert sx.get(j['id'])['state']==expected
