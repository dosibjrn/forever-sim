from pathlib import Path
import time

from src.service.models import JobRequest
from src.service.store import QueueStore


def _req():
    return JobRequest(ruleset="forever", class_name="mage", start_level=11, end_level=60, endpoint_mode="mc")


def test_status_snapshot_exposes_durable_progress_best_and_heartbeat_health(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    job,_=store.enqueue(_req(),deduplicate=False)
    claimed=store.claim_next(owner="u2",runs_root=tmp_path/"runs",lease_seconds=20,max_active_jobs=1,max_resource_units=1)
    assert claimed is not None
    running,attempt=claimed
    store.record_event(job["id"],"runtime_progress",{
        "attempt_id":attempt["id"],"phase":"preview_validation","stage":"validate",
        "level":40,"progress":{"mode":"determinate","current":25,"total":100,"fraction":0.25,"unit":"rows"},
        "best_so_far":{"best_validated_hours":12.345,"candidate_id":"cand-1"},"message":"validating",
    })
    snap=store.status_snapshot(); row=next(x for x in snap["jobs"] if x["id"]==job["id"])
    assert row["phase"]=="preview_validation"
    assert row["stage"]=="validate"
    assert row["progress"]=={"mode":"determinate","current":25,"total":100,"fraction":0.25,"unit":"rows"}
    assert row["best_so_far"]["candidate_id"]=="cand-1"
    assert row["runtime_level"]==40
    assert row["heartbeat"]["stalled"] is False
    assert row["heartbeat"]["age_seconds"] is not None


def test_smooth_running_job_reports_indeterminate_not_fake_percentage(tmp_path: Path):
    store=QueueStore(tmp_path/"q.sqlite3")
    req=JobRequest(ruleset="forever",class_name="paladin",start_level=20,end_level=30,endpoint_mode="smooth")
    job,_=store.enqueue(req,deduplicate=False)
    claimed=store.claim_next(owner="u2",runs_root=tmp_path/"runs",lease_seconds=20,max_active_jobs=1,max_resource_units=1)
    assert claimed is not None
    store.record_event(job["id"],"runtime_progress",{"attempt_id":claimed[1]["id"],"phase":"starting","stage":"v2_runner","progress":{"mode":"indeterminate"},"best_so_far":None})
    row=next(x for x in store.status_snapshot()["jobs"] if x["id"]==job["id"])
    assert row["progress"]=={"mode":"indeterminate"}
    assert row["best_so_far"] is None


def test_scheduler_normalizes_attempt_runtime_status_without_log_parsing(tmp_path: Path):
    from src.service.scheduler import Scheduler
    run_root=tmp_path/"run"
    status=run_root/"state"/"games"/"forever-mage"/"runtime"/"status.json"
    status.parent.mkdir(parents=True)
    status.write_text('''{"state":"validating_preview","phase":"preview_validation","outer_stage":"validate","validation_done":5,"validation_total":20,"validation_level":33,"message":"working","best":{"best_validated_hours":9.5,"candidate_id":"c9","source":"probe"}}''')
    payload=Scheduler._runtime_progress_payload({"request":{}},{"id":"a1","run_root":str(run_root)})
    assert payload["phase"]=="preview_validation"
    assert payload["stage"]=="validate"
    assert payload["level"]==33
    assert payload["progress"]=={"mode":"determinate","current":5,"total":20,"fraction":0.25,"unit":"rows"}
    assert payload["best_so_far"]=={"best_validated_hours":9.5,"candidate_id":"c9","source":"probe"}
