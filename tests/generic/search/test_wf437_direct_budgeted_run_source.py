"""WF437 full-runner source initialization uses the canonical checkpoint DB."""
from __future__ import annotations

import json
import runpy
import sys
from hashlib import sha256
from pathlib import Path

from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.v2 import source_bounded_joint_frontier as frontier


ROOT = Path(__file__).resolve().parents[3]
RUNNER = ROOT / "tools" / "wf437_direct_budgeted_run.py"


def test_druid_l30_full_runner_uses_canonical_db_and_reaches_cold_search(
        monkeypatch, tmp_path):
    canonical = Path(DEFAULT_DB).resolve()
    assert canonical.is_file()

    observed = {}

    def capture_search(**kwargs):
        observed.update(kwargs)
        # The test verifies real source initialization and the production
        # search boundary; it does not fabricate a search result or gate PASS.
        return {
            "wall_s": 0.001,
            "paid_candidates": 0,
            "unique_full_builds": 0,
            "screen_complete_candidates": 0,
            "search_winner": None,
            "refinement": {
                "rounds_completed": 0,
                "stat_probes": 0,
                "gear_probes": 0,
            },
            "validation_shortlist": [],
            "source_slot_proposal_coverage": {
                "strategy": "canonical_source_init_test",
            },
        }

    monkeypatch.setattr(frontier, "search_bounded_joint_frontier", capture_search)
    output = tmp_path / "druid-l30-p4-source.json"
    monkeypatch.setattr(sys, "argv", [
        str(RUNNER), "--budget", "30", "--output", str(output),
    ])

    runpy.run_path(str(RUNNER), run_name="__main__")

    report = json.loads(output.read_text())
    assert Path(report["source_db_path"]).resolve() == canonical
    assert report["source_db_sha256"] == sha256(canonical.read_bytes()).hexdigest()
    assert "staged_druid_l30_talents_70338.sqlite" not in report["source_db_path"]

    # These are real objects built from DEFAULT_DB, not mocked IR/gear inputs.
    assert observed["class_key"] == "druid"
    assert observed["level"] == 30
    assert observed["source_ir"] is not None
    assert observed["source_ir"].talents
    assert observed["seed_stage"] is not None
    assert report["source_search_space"]["gear_role"] == "druid_feral"

    # Preserve the actual P4 cold-search contract at the production boundary.
    assert observed["max_cpu_s"] == 30.0
    assert observed["max_paid_builds"] == 1000
    assert observed["screen_mobs"] == 2
    assert observed["finalist_mobs"] == 100
    assert observed["search_only"] is True
    assert "spec_tree" not in observed
    assert "min_spec_points" not in observed
