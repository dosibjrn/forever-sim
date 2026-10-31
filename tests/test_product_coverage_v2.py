"""WF-P00a negative gates and live executable 1–60 product audit."""
import copy
import json
from pathlib import Path

import pytest

from scripts.audit_product_coverage import (
    CLASSES, STATUSES, audit, classify_level, full_optimization_blockers,
    inspect_snapshot,
)


def test_540_rows_live_and_no_ir_to_optimized_promotion():
    report = audit()
    assert len(report["rows"]) == 9 * 60
    assert {r["class"] for r in report["rows"]} == set(CLASSES)
    assert all(sum(report["summary"][c][s] for s in STATUSES) == 60 for c in CLASSES)
    assert report["summary"]["druid"]["source_ir_executed"] == 60
    assert report["summary"]["paladin"]["source_ir_executed"] == 21
    assert report["summary"]["hunter"]["source_ir_executed"] == 11
    assert report["summary"]["druid"]["queue_source_only_declared"] == 2
    assert all(report["summary"][c]["fully_optimized"] == 0 for c in CLASSES)
    assert report["contradictory_default_declarations"] == []


def test_real_bounded_route_scored_not_product_route_complete():
    report = audit()
    lookup = {(r["class"], r["level"]): r for r in report["rows"]}
    assert all(lookup["druid", n]["status"] == "evaluated" for n in range(10, 21))
    assert all(lookup["rogue", n]["status"] == "evaluated" for n in range(10, 21))
    assert all(lookup["warrior", n]["status"] == "evaluated" for n in range(10, 21))
    assert all(lookup["warlock", n]["status"] == "evaluated" for n in range(10, 19))
    assert lookup["warlock", 19]["status"] == "source_only"
    assert lookup["druid", 21]["status"] == "evaluated"
    assert lookup["mage", 10]["status"] == "evaluated"
    assert lookup["druid", 12]["queue_source_only_declared"] is False
    assert lookup["druid", 12]["bounded_native_evaluation"] is True
    assert lookup["druid", 10]["complete_timing"] is False
    assert report["bounded_source_scenario_routes"]["full_L10_to_L20_corridors"] == 8
    assert report["bounded_source_scenario_routes"]["fullpoint_Druid_L1_to_L60_bounded_reference"] is True
    assert report["bounded_source_scenario_routes"]["distinct_source_scenario_evaluated_level_slices"] == 146
    assert report["bounded_source_scenario_routes"]["scratch_verified_source_scenario_steps"] == 97
    assert report["bounded_source_scenario_routes"]["complete_leveling_routes"] == 0
    assert sum(s["validated"] for s in report["summary"].values()) == 0


def test_ir_and_queue_declaration_do_not_fake_evaluation():
    assert classify_level(source_ir=True, route_step=None)[0] == "source_only"
    assert classify_level(source_ir=False, route_step={"seconds_per_mob": 3, "legacy_fallback": False})[0] == "unsupported"
    assert classify_level(source_ir=True, route_step={"seconds_per_mob": 3, "legacy_fallback": True})[0] == "source_only"


def test_missing_gear_and_weights_cannot_be_optimized():
    step = {"legacy_fallback": False, "seconds_per_mob": 8,
            "policy_ir": {"rules": ["cast"]}, "fixed_point_converged": True,
            "gear_stats": {}, "stat_weights": {},
            "timing": {"timing_complete": True, "timing_consistent": True,
                       "travel_seconds_per_mob": 1, "recovery_seconds_per_mob": 2},
            "optimization_evidence": {"producer": "joint_generic_gear_talent_policy_optimizer",
                                      "evaluated_candidate_count": 4,
                                      "legal_talents_and_gear": True,
                                      "recovery_and_survival_risk": True}}
    assert "attainable_selected_gear_not_proven" in full_optimization_blockers(step)
    assert "stat_sensitivity_not_proven" in full_optimization_blockers(step)
    assert classify_level(source_ir=True, route_step=step,
                          complete_route_proof=True, independent_reference_proof=True)[0] == "evaluated"


def test_stale_or_mismatched_snapshot_cannot_promote(tmp_path):
    report = audit()
    path = Path("data/forever/generic_druid_route_publication_v1.json")
    data = json.loads(path.read_text())
    data["software_version"] = "0.11.48.0"
    bad = tmp_path / "stale.json"
    bad.write_text(json.dumps(data))
    check = inspect_snapshot(bad, version=report["software_version"],
                             db_sha=report["canonical_item_db_sha256"],
                             schema=data["schema_version"], levels=data["levels"],
                             authority=data["route_authority"])
    assert check["valid"] is False and "version" in check["failures"]
    data["software_version"] = report["software_version"]
    data["canonical_item_db_sha256"] = "0" * 64
    bad.write_text(json.dumps(data))
    check = inspect_snapshot(bad, version=report["software_version"],
                             db_sha=report["canonical_item_db_sha256"],
                             schema=data["schema_version"], levels=data["levels"],
                             authority=data["route_authority"])
    assert check["valid"] is False and "canonical_item_db" in check["failures"]


def test_forged_optimizer_flag_alone_does_not_promote():
    step = {"legacy_fallback": False, "seconds_per_mob": 4,
            "optimization_evidence": {"producer": "joint_generic_gear_talent_policy_optimizer",
                                      "evaluated_candidate_count": 60}}
    assert classify_level(source_ir=True, route_step=step)[0] == "evaluated"


def test_stale_snapshot_removes_scored_druid_levels(tmp_path):
    from scripts.audit_product_coverage import _bounded_steps
    src = Path("data/forever/generic_druid_route_publication_v1.json")
    dest = tmp_path / "data/forever/generic_druid_route_publication_v1.json"
    dest.parent.mkdir(parents=True)
    payload = json.loads(src.read_text())
    payload["software_version"] = "0.11.48.0"
    dest.write_text(json.dumps(payload))
    # Missing melee cache also fails closed; no live optimizer is triggered.
    report = audit()
    snapshots, steps = _bounded_steps(tmp_path, report["software_version"],
                                      report["canonical_item_db_sha256"])
    assert snapshots["druid"]["valid"] is False
    assert "version" in snapshots["druid"]["failures"]
    assert "druid" not in steps
