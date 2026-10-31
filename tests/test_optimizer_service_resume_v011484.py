from pathlib import Path
import json

from src.service.checkpoints import build_manifest, stage_resume_checkpoint, select_resume_checkpoint
from src.service.models import JobRequest, JobState
from src.service.scheduler import Scheduler
from src.service.store import QueueStore


def req(**kw):
    base=dict(ruleset="forever", class_name="mage", start_level=11, end_level=60,
              endpoint_mode="mc", source_snapshot="beta-20260924",
              engine_semantic_hash="engine-a", policy_space_version="p1",
              config={"school":"frost", "water_mode":"buy_water"})
    base.update(kw)
    return JobRequest(**base)


def make_checkpoint(store: QueueStore, job: dict, attempt: dict, *, body=b"resume-state"):
    cp=Path(attempt["run_root"])/"state"/"tracks"/"buy_water"/"checkpoints"/"buy_frost_exp_00000_tier0.pkl"
    cp.parent.mkdir(parents=True, exist_ok=True); cp.write_bytes(body)
    controller=Path(attempt["run_root"])/"state"/"runtime"/"controller.json"
    controller.parent.mkdir(parents=True, exist_ok=True); controller.write_text('{"version":4,"marker":"same-experiment"}')
    config=Path(attempt["run_root"])/"state"/"config.json"; config.write_text('{"max_respecs":2}')
    manifest=build_manifest(job=job, attempt=attempt, path=cp)
    return store.record_checkpoint(manifest.to_dict())


def test_select_resume_prefers_same_job_and_excludes_seed_only(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    a,_=store.enqueue(req(), deduplicate=False)
    aa=store.claim_next(owner="a", runs_root=tmp_path/"runs")[1]
    own=make_checkpoint(store,a,aa)
    store.finish_attempt(aa["id"], owner="a", outcome="paused")

    b,_=store.enqueue(req(engine_semantic_hash="engine-b"), deduplicate=False)
    bb=store.claim_next(owner="b", runs_root=tmp_path/"runs")[1]
    seed=make_checkpoint(store,b,bb,body=b"seed-only")
    store.finish_attempt(bb["id"], owner="b", outcome="paused")

    picked=select_resume_checkpoint(store.list_checkpoints(), a["request"], prefer_job_id=a["id"])
    assert picked["id"] == own["id"]
    assert picked["id"] != seed["id"]


def test_stage_resume_copies_checkpoint_and_minimal_runtime_state(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    job,_=store.enqueue(req())
    src=store.claim_next(owner="a", runs_root=tmp_path/"runs")[1]
    cp=make_checkpoint(store,job,src)
    store.finish_attempt(src["id"], owner="a", outcome="paused")
    store.transition(job["id"], JobState.QUEUED)
    dst=store.claim_next(owner="b", runs_root=tmp_path/"runs")[1]
    info=stage_resume_checkpoint(checkpoint=cp, source_attempt=src, target_attempt=dst)
    staged=Path(info["staged_path"])
    assert staged.read_bytes() == b"resume-state"
    assert Path(dst["run_root"],"state/runtime/controller.json").exists()
    assert Path(dst["run_root"],"state/config.json").exists()
    assert staged != Path(cp["path"])


def test_scheduler_stages_resume_before_executor_launch_contract(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    job,_=store.enqueue(req())
    first=store.claim_next(owner="a", runs_root=tmp_path/"runs")[1]
    cp=make_checkpoint(store,job,first)
    store.finish_attempt(first["id"], owner="a", outcome="paused")
    store.transition(job["id"], JobState.QUEUED)

    sched=Scheduler(store,runs_root=tmp_path/"runs",owner="b")
    claimed=sched.claim(); assert claimed is not None
    info=sched._stage_resume(claimed.job, claimed.attempt)
    assert info and info["checkpoint_id"] == cp["id"]
    assert Path(info["staged_path"]).exists()
    events=store.events(job["id"])
    assert any(e["kind"] == "checkpoint_staged_for_resume" for e in events)
