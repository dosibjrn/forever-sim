"""Issue #61 M1: real sequential gsim pull trace audit (NOT native ACK)."""
from copy import deepcopy

import pytest

from src.v2.persistent_pull_trace_audit import audit_persistent_pull_trace


def _two_realistic_pulls():
    return [
        {"mob": 1, "target_id": "mob_1", "pull_started_s": 0.0,
         "kill_finished_s": 3.0, "recovery_s": 2.0,
         "recovery_finished_s": 5.0},
        {"mob": 2, "target_id": "mob_2", "pull_started_s": 5.5,
         "kill_finished_s": 9.0, "recovery_s": 1.0,
         "recovery_finished_s": 10.0},
    ]


def test_real_persistent_trace_requires_distinct_monotonic_kills():
    report = audit_persistent_pull_trace(_two_realistic_pulls(), expected_mobs=2)
    assert report["status"] == "GSIM_PERSISTENT_TRACE_INVARIANTS_ONLY"
    assert report["distinct_targets"] == 2
    assert report["native_world_action_ack_verified"] is False


@pytest.mark.parametrize("mutation", [
    lambda rows: rows[1].update(target_id="mob_1"),
    lambda rows: rows[1].update(mob=3),
    lambda rows: rows[1].update(pull_started_s=4.0),
    lambda rows: rows[1].update(kill_finished_s=5.0),
    lambda rows: rows[0].update(recovery_finished_s=3.5),
    lambda rows: rows[0].update(recovery_s=float("nan")),
    lambda rows: rows[0].pop("target_id"),
])
def test_reject_fabricated_or_inconsistent_persistent_trace(mutation):
    rows=deepcopy(_two_realistic_pulls())
    mutation(rows)
    with pytest.raises(ValueError, match="PERSISTENT_TRACE_"):
        audit_persistent_pull_trace(rows, expected_mobs=2)


def test_reject_missing_or_extra_mob_without_claiming_100_kills():
    rows=_two_realistic_pulls()
    for invalid in (rows[:1], rows+rows[:1]):
        with pytest.raises(ValueError, match="PERSISTENT_TRACE_MOB_COUNT_MISMATCH"):
            audit_persistent_pull_trace(invalid, expected_mobs=2)


def test_bad_expected_mob_count_is_not_a_certificate():
    for invalid in (0, True, -1):
        with pytest.raises(ValueError, match="PERSISTENT_TRACE_INVALID_EXPECTED_MOBS"):
            audit_persistent_pull_trace([], expected_mobs=invalid)


def test_hundred_distinct_pulls_keep_one_monotonic_clock_without_native_claim():
    rows=[]
    for i in range(100):
        start=float(i*10)
        rows.append({"mob":i+1, "target_id":f"mob_{i+1}",
                     "pull_started_s":start, "kill_finished_s":start+4,
                     "recovery_s":6.0, "recovery_finished_s":start+10})
    report=audit_persistent_pull_trace(rows, expected_mobs=100)
    assert report["distinct_targets"]==100
    assert report["native_world_action_ack_verified"] is False
