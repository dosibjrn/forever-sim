from pathlib import Path

from src.service.checkpoints import Compatibility, build_manifest, classify_compatibility, discover_checkpoint_files, write_sidecar
from src.service.models import JobRequest
from src.service.scheduler import Scheduler
from src.service.store import QueueStore


def request(**kw):
    base=dict(ruleset="forever",class_name="mage",start_level=11,end_level=60,endpoint_mode="mc",source_snapshot="beta-20260924",engine_semantic_hash="engine-a",policy_space_version="p1",config={"school":"frost"})
    base.update(kw)
    return JobRequest(**base)


def test_checkpoint_compatibility_is_strict_for_resume_and_safe_for_seed():
    a=request().canonical_dict()
    assert classify_compatibility(a,dict(a)) is Compatibility.RESUME
    b=dict(a); b["engine_semantic_hash"]="engine-b"
    assert classify_compatibility(a,b) is Compatibility.SEED_ONLY
    c=dict(a); c["class_name"]="paladin"
    assert classify_compatibility(a,c) is Compatibility.INCOMPATIBLE
    d=dict(a); d["endpoint_mode"]="smooth"
    assert classify_compatibility(a,d) is Compatibility.INCOMPATIBLE


def test_manifest_hash_sidecar_and_store_are_durable(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    job,_=store.enqueue(request())
    claimed=store.claim_next(owner="d",runs_root=tmp_path/"runs")
    attempt=claimed[1]
    cp=Path(attempt["run_root"])/"state"/"tracks"/"buy_water"/"checkpoints"/"x.pkl"
    cp.parent.mkdir(parents=True); cp.write_bytes(b"checkpoint-bytes")
    manifest=build_manifest(job=job,attempt=attempt,path=cp)
    sidecar=write_sidecar(manifest)
    row=store.record_checkpoint(manifest.to_dict())
    assert sidecar.exists()
    assert row["sha256"] == manifest.sha256
    assert store.list_checkpoints(job["id"])[0]["path"] == str(cp)
    # reopening DB proves this is control-plane state, not process memory
    assert QueueStore(tmp_path/"q.sqlite3").list_checkpoints(job["id"])[0]["sha256"] == manifest.sha256


def test_scheduler_checkpoint_discovery_records_attempt_artifacts(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    job,_=store.enqueue(request())
    sched=Scheduler(store,runs_root=tmp_path/"runs",owner="d")
    claimed=sched.claim(); assert claimed is not None
    cp=Path(claimed.attempt["run_root"])/"state"/"checkpoints"/"resume.pkl"
    cp.parent.mkdir(parents=True); cp.write_bytes(b"abc")
    rows=sched._record_checkpoints(claimed.job,claimed.attempt)
    assert len(rows)==1
    assert rows[0]["attempt_id"] == claimed.attempt["id"]
    assert discover_checkpoint_files(claimed.attempt["run_root"]) == [cp]
    # idempotent scan doesn't duplicate rows
    sched._record_checkpoints(claimed.job,claimed.attempt)
    assert len(store.list_checkpoints(job["id"])) == 1
