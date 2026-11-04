"""Work1: one real 300s producer preserves an honest paid 30s frontier."""
from types import SimpleNamespace

import pytest

from src.v2 import source_bounded_joint_frontier as frontier
from tools import wf_gate_p4_p5_partial as gate


def _paid_row(name, elapsed, score):
    return {
        "allocation": {},
        "gear_move": name,
        "policy": "source-native-policy",
        "policy_signature": "source-native-policy-" + name,
        "recovery": "native",
        "screen_invoked": True,
        "screen_status": "COMPLETE",
        "screen_s_per_mob": score,
        "screen_events": 4,
        "equipped_gear": {"slots": {"head": {"item_id": len(name)}}},
        "opening_action_ids": [name],
        "paid_completed_elapsed_s": elapsed,
    }


def test_paid_snapshot_excludes_faster_300s_only_candidates_and_is_immutable():
    early = _paid_row("before", 29.8, 8.0)
    late = _paid_row("after", 30.01, 2.0)
    attempted = [early, late]
    screened = [(early, SimpleNamespace(), "native"),
                (late, SimpleNamespace(), "native")]
    snapshot = frontier._paid_30s_snapshot(attempted, screened)

    assert snapshot["source"] == "PAID_SCREEN_COMPLETION_CLOCK"
    assert snapshot["cutoff_elapsed_s"] == 30
    assert snapshot["winner"]["paid_candidate_index"] == 0
    assert snapshot["winner"]["screen_s_per_mob"] == 8.0
    assert snapshot["paid_candidates_before_cutoff"] == 1
    assert snapshot["paid_candidates_after_cutoff"] == 1
    assert snapshot["unique_full_builds_before_cutoff"] == 1
    early["screen_s_per_mob"] = 1.0
    assert snapshot["winner"]["screen_s_per_mob"] == 8.0


def test_snapshot_never_selects_unpaid_or_failed_faster_candidate():
    unpaid = _paid_row("unpaid", 20.0, 1.0)
    unpaid["screen_invoked"] = False
    refused = _paid_row("refused", 27.0, 1.5)
    refused["screen_status"] = "BLOCKED"
    valid = _paid_row("valid", 29.0, 9.0)
    snapshot = frontier._paid_30s_snapshot(
        [unpaid, refused, valid], [(valid, SimpleNamespace(), "native")])
    assert snapshot["winner"]["gear_move"] == "valid"
    assert snapshot["paid_candidates_before_cutoff"] == 2
    assert snapshot["unique_full_builds_before_cutoff"] == 2


@pytest.mark.parametrize("gate_key", ["P4", "P5"])
def test_full_gate_launches_only_one_continuing_300s_cold_search(
        monkeypatch, tmp_path, gate_key):
    from tools import wf_gate_p6_full_source as subprocess_entry
    calls = []

    def fake_execute(root, args, output, timeout_s):
        calls.append((list(args), timeout_s))
        # Real producer returns a structured failure before paid replay.
        return {"status": "FAIL", "validation_shortlist": []}, None

    monkeypatch.setattr(subprocess_entry, "_execute", fake_execute)
    result = gate.run_full_paid_source_search(
        tmp_path, "priest", 20, spec="unrestricted", gate=gate_key)
    assert result["status"] == "FAIL"
    assert calls == [(["--budget", "300", "--checkpoint-class", "priest",
                       "--checkpoint-level", "20", "--checkpoint-spec",
                       "unrestricted"], 720)]


def _two_window_paid_report():
    """Real receipt shapes, synthetic data: test adapter mapping, not game rules."""
    def build(candidate_id):
        return {
            "paid_candidate_index": candidate_id,
            "allocation": {},
            "equipped_gear": {"slots": {}},
            "opening_action_ids": ["585"],
            "policy_ir": {"id": "candidate-" + str(candidate_id)},
            "policy_signature": "candidate-" + str(candidate_id),
            "recovery": "native",
        }

    return {
        "class_key": "priest", "level": 20, "search_only": True,
        "requested_wall_budget_s": 300, "wall_s": 300,
        "source_db_sha256": "a" * 64,
        "source_gear_catalogue_snapshot": {"class_membership_verified": True},
        "source_search_space": {
            "class_key": "priest", "level": 20,
            "checkpoint_spec": "unrestricted",
        },
        "spatial_mode": "simultaneous_2d_pack", "pack_size": 2,
        "p4_talent_unlock_coverage": {},
        "unique_full_builds": 2, "screen_complete_candidates": 2,
        "source_legal_gear_universe_verified": True,
        "snapshot_30": {
            "winner": build(0), "cutoff_elapsed_s": 30,
            "validation_shortlist_index": 0,
            "paid_candidates_after_cutoff": 1,
            "unique_full_builds_before_cutoff": 1,
            "source": "PAID_SCREEN_COMPLETION_CLOCK",
        },
        "validation_shortlist": [build(0), build(1)],
        "validation": {
            "validated_winner_id": "1",
            "rows": [
                {"id": "0", "status": "COMPLETE", "count": 100,
                 "mob_completed": 100, "full_s_per_mob": 9.0},
                {"id": "1", "status": "COMPLETE", "count": 100,
                 "mob_completed": 100, "full_s_per_mob": 4.0},
            ],
        },
    }


def _mock_cold_receipts(monkeypatch, report):
    from tools import wf_gate_p6_full_source as subprocess_entry
    from src.v2 import source_paid_cold_comparison as comparison

    monkeypatch.setattr(subprocess_entry, "_execute",
                        lambda *args: (report, None))
    # Native/source game legality is not being retested by an adapter test:
    # this fixture isolates which paid replay the gate actually consumes.
    monkeypatch.setattr(comparison, "source_gear_catalogue_snapshot",
                        lambda *args: report["source_gear_catalogue_snapshot"])
    monkeypatch.setattr(comparison, "_verify_winner_gear_legality",
                        lambda *args, **kwargs: {"equipment_legality_complete": True})
    monkeypatch.setattr(comparison, "_winner_gear_effect_gaps",
                        lambda *args, **kwargs: {})


@pytest.mark.parametrize("gate_key, expected_time",
                         [("P4", 9.0), ("P5", 4.0)])
def test_gate_uses_own_30s_or_300s_winner_100mob_receipt(
        monkeypatch, tmp_path, gate_key, expected_time):
    report = _two_window_paid_report()
    _mock_cold_receipts(monkeypatch, report)

    result = gate.run_full_paid_source_search(
        tmp_path, "priest", 20, spec="unrestricted", gate=gate_key)

    assert result["status"] == "PASS"
    assert result["real_100mob_s_per_mob"] == expected_time
    assert [r["s_per_mob"] for r in
            result["p4_p5_100mob_winner_replays"]] == [9.0, 4.0]


def test_p4_never_borrows_later_winners_completed_100mob_replay(
        monkeypatch, tmp_path):
    report = _two_window_paid_report()
    report["validation"]["rows"][0].update(
        status="INCOMPLETE", count=6, mob_completed=6, full_s_per_mob=None)
    _mock_cold_receipts(monkeypatch, report)

    result = gate.run_full_paid_source_search(
        tmp_path, "priest", 20, spec="unrestricted", gate="P4")

    assert result["status"] == "FAIL"
    assert "P4_INCOMPLETE_PAID_100MOB_FINALIST" in result["reasons"]
    assert result["real_100mob_count"] == 0
    assert result["real_100mob_s_per_mob"] is None
    assert result["p4_p5_100mob_winner_replays"][1]["count"] == 100


def test_p4_rejects_a_count_100_receipt_with_99_actual_mobs(
        monkeypatch, tmp_path):
    report = _two_window_paid_report()
    report["validation"]["rows"][0]["mob_completed"] = 99
    _mock_cold_receipts(monkeypatch, report)

    result = gate.run_full_paid_source_search(
        tmp_path, "priest", 20, spec="unrestricted", gate="P4")

    assert result["status"] == "FAIL"
    assert "P4_INCOMPLETE_PAID_100MOB_FINALIST" in result["reasons"]


def test_p4_snapshot_cannot_point_at_unrelated_later_candidate(
        monkeypatch, tmp_path):
    report = _two_window_paid_report()
    report["snapshot_30"]["validation_shortlist_index"] = 1
    _mock_cold_receipts(monkeypatch, report)

    result = gate.run_full_paid_source_search(
        tmp_path, "priest", 20, spec="unrestricted", gate="P4")

    assert result["status"] == "FAIL"
    assert "P4_REAL_30S_FROZEN_PAID_WINNER_MISSING" in result["reasons"]
