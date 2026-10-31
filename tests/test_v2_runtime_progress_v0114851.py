import json
import time
from pathlib import Path

from src.v2 import runtime_progress as rp
from src.v2.runtime_progress import progress_scope
from src.service.scheduler import Scheduler


def test_runtime_progress_writes_determinate_candidate_and_fixed_point_status(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rp, "STATE_DIR", tmp_path)
    monkeypatch.setattr(rp, "_LAST_WRITE_AT", 0.0)
    started=time.time()-120
    with progress_scope(
        phase="searching", started_at=started, levels_done=2, levels_total=10,
        level=13, candidate_current=8, candidate_total=20, profile="bear",
    ):
        payload=rp.emit_runtime_progress(
            force=True, stage="fixed_point", fixed_point_iteration=2, fixed_point_max_iters=4,
        )
    assert payload is not None
    raw=json.loads((tmp_path/"runtime"/"status.json").read_text())
    assert raw["level"]==13
    assert raw["outer_stage"]=="fixed_point"
    assert raw["progress"]["mode"]=="determinate"
    assert 0.2 < raw["progress"]["fraction"] < 0.3
    assert raw["candidate_current"]==8 and raw["candidate_total"]==20
    assert raw["profile"]=="bear"
    assert raw["fixed_point_iteration"]==2
    assert "candidate 8/20" in raw["message"]
    assert "fixed-point 2/4" in raw["message"]
    assert "ETA ~" in raw["message"]


def test_scheduler_accepts_generic_v2_progress_payload(tmp_path: Path):
    run_root=tmp_path/"run"
    status=run_root/"state"/"games"/"forever-druid"/"v2"/"runtime"/"status.json"
    status.parent.mkdir(parents=True)
    status.write_text(json.dumps({
        "state":"running", "phase":"searching", "outer_stage":"fixed_point", "level":17,
        "progress":{"mode":"determinate","current":6,"total":10,"fraction":0.64,"unit":"levels"},
        "message":"L17 · candidate 12/25 · balance · fixed-point 3/4 · ETA ~2m 10s",
    }))
    payload=Scheduler._runtime_progress_payload({"request":{}},{"id":"a1","run_root":str(run_root)})
    assert payload["phase"]=="searching"
    assert payload["stage"]=="fixed_point"
    assert payload["level"]==17
    assert payload["progress"]["fraction"]==0.64
    assert "candidate 12/25" in payload["message"]
