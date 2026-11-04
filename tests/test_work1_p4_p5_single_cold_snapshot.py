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
