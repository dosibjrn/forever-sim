"""Full-source paid P4/P5 receipts must survive canonical gate CLI masking.

Regression for actual Druid L60 Balance P4 30s Actions #41502526876:
before this patch, three FAIL reasons survived but no executed 30s or paid
100-mob finalist measurements did. This is reporting, NOT gate acceptance.
"""
import json
from tools import wf_gate


def test_p4_real_search_and_finalist_receipts_survive_no_record_gate(monkeypatch, capsys):
    report = {
        "status": "FAIL",
        "reasons": [
            "P4_SELECTED_NATIVE_2D_WORLD_BACKEND_NOT_VERIFIED",
            "P4_SOURCE_LEGAL_SPACE_COMPLETENESS_NOT_PROVEN"],
        "production_engine": "gsim_CombatRuntime",
        "requested_wall_budget_s": 30,
        "real_search_wall_s": 29.7,
        "real_paid_unique_full_builds": 41,
        "real_paid_screen_complete": 35,
        "real_100mob_complete": True,
        "real_100mob_count": 100,
        "real_100mob_s_per_mob": 17.2,
        "saved_full_source_winner_build": True,
        "winning_gear_source_legality_verified": True,
        "source_class_gear_membership_attested": False,
        "source_gear_catalogue_snapshot": {"private_bulk": "do not expose"},
        "real_talent_unlocked_actions": {"bulky": ["do not expose"]},
    }
    monkeypatch.setattr(wf_gate, "_run_live_gate", lambda *args: report)
    assert wf_gate.main(["--class", "druid", "--level", "60", "--spec",
                         "balance", "--gate", "P4"]) == 1
    output = json.loads(capsys.readouterr().out)
    row = output["results"][0]
    assert output["status"] == "FAIL"
    assert row["reasons"] == report["reasons"]
    assert {key: row[key] for key in (
        "requested_wall_budget_s", "real_search_wall_s",
        "real_paid_unique_full_builds", "real_paid_screen_complete",
        "real_100mob_complete", "real_100mob_count", "real_100mob_s_per_mob",
        "saved_full_source_winner_build",
        "winning_gear_source_legality_verified",
        "source_class_gear_membership_attested")} == {
        key: report[key] for key in (
        "requested_wall_budget_s", "real_search_wall_s",
        "real_paid_unique_full_builds", "real_paid_screen_complete",
        "real_100mob_complete", "real_100mob_count", "real_100mob_s_per_mob",
        "saved_full_source_winner_build",
        "winning_gear_source_legality_verified",
        "source_class_gear_membership_attested")}
    assert "source_gear_catalogue_snapshot" not in row
    assert "real_talent_unlocked_actions" not in row
    assert "pass_count" not in row
    assert "partial_coverage_percent" not in row


def test_p5_numbers_are_bounded_and_false_stays_false(monkeypatch, capsys):
    report = {
        "status": "FAIL", "reasons": ["P5_INDEPENDENT_COLD_SOURCE_SPACE_NOT_MATCHED"],
        "production_engine": "gsim_CombatRuntime",
        "requested_wall_budget_s": 300,
        "real_search_wall_s": float("inf"),
        "real_paid_unique_full_builds": True,
        "real_paid_screen_complete": 900,
        "real_100mob_complete": False,
        "real_100mob_count": float("nan"),
        "independent_N30_unique_paid": 30,
        "independent_N300_unique_paid": 45,
        "independent_p5_2x_or_exhaustion_breadth": False,
        "independent_same_source_candidate_space": False,
        "independent_100mob_winner_replays_complete": False,
        "extra_arbitrary_diagnostics": "not exported",
    }
    monkeypatch.setattr(wf_gate, "_run_live_gate", lambda *args: report)
    assert wf_gate.main(["--class", "druid", "--level", "60", "--spec",
                         "balance", "--gate", "P5"]) == 1
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["requested_wall_budget_s"] == 300
    assert "real_paid_unique_full_builds" not in row
    assert row["real_100mob_complete"] is False
    assert row["independent_N30_unique_paid"] == 30
    assert row["independent_N300_unique_paid"] == 45
    assert row["independent_p5_2x_or_exhaustion_breadth"] is False
    assert "real_search_wall_s" not in row
    assert "real_100mob_count" not in row
    assert "extra_arbitrary_diagnostics" not in row
