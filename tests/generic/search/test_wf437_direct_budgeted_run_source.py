"""WF437 full-runner source initialization uses the canonical checkpoint DB."""
from __future__ import annotations

import json
import runpy
import sys
from hashlib import sha256
from pathlib import Path

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.sqlite_talents import DEFAULT_DB
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.v2 import source_bounded_joint_frontier as frontier
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate


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



def test_canonical_druid_l30_source_still_generates_and_executes_insect_swarm():
    # The missing staged DB used to supply a checkpoint talent catalogue.
    # Prove the canonical DB alone still supplies the actual talent grant and
    # its ordinary paid combat execution; no staged source is reconstructed.
    canonical = Path(DEFAULT_DB).resolve()
    raw = build_game_ir_slice(
        class_key="druid", level=30, ability_db_path=canonical)
    assert raw is not None
    source = compile_talent_runtime(raw)[0]
    stage = frontier.source_cold_start_stage(
        class_key="druid", level=30, source_ir=source, gear_role="druid_feral")

    allocations, _ = frontier.bounded_full_point_talent_frontier(
        source, level=30, bonus_talent_points=5, max_frontier=16)
    allocation = next(
        (row for row in allocations if row.get("insect_swarm") == 1), None)
    assert allocation is not None, "canonical source lacks the L30 Insect Swarm talent facts"

    selected, _ = apply_talent_selection(
        source, allocation, level=30, bonus_talent_points=5)
    assert "insect_swarm:24974" in {action.id for action in selected.actions}

    witness = next(
        row for row in frontier.source_talent_unlock_witnesses(
            source, selected, stage)
        if row["action_id"] == "insect_swarm:24974")
    candidate = frontier._prepare_joint_policy_candidate(
        class_key="druid", level=30, stage=stage, allocation=allocation,
        source_ir=source, allow_partial_gear_stats=True,
        policy_label="talent_unlock:insect_swarm:24974",
        policy=witness["policy"], bonus_talent_points=5)
    result = evaluate_persistent_candidate(
        candidate, level=30, mobs=4, max_total_events=200000)
    assert result["status"] == "COMPLETE", result
    assert result["source_action_counts"]["insect_swarm:24974"] > 0
    assert result["source_action_counts"]["wrath:5180"] > 0
