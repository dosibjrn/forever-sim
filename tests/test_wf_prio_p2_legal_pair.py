"""Real source P2 regression: full-point search builds are not always legal paired controls.

The source-legal Balance profile can contain a Restoration tier-3 talent
whose unlock depends on Gift of Nature rank 2. Its rank-1 control must be
evaluated on a *different legal partial allocation*, while the optimizer's
full-point search witness remains independently verified.
"""
from pathlib import Path

from tools.wf_gate_p2_live import run_live
from src.game.talents import available_talent_points


def test_druid_l60_gift_of_nature_rank_two_has_legal_paired_runtime_control():
    report = run_live(Path(__file__).resolve().parents[1], "druid", 60, spec="balance")
    rows = {row["rank_key"]: row for row in report["ranks"]}
    row = rows["gift_of_nature:2"]

    # An illegal rank-1 predecessor must not be accepted, but neither should
    # it prevent testing the rank's real effect in a valid partial setup.
    assert row["status"] == "PASS", row["reasons"]
    assert row["behavior_tests"], "structural talent acceptance is not behavior"
    assert all(test["actually_executed"] and test["passed"]
               for test in row["behavior_tests"])
    assert row["search_reachable"] is True
    assert row["spec_full_point_exact_rank_witness"] is True

    # The selected paired runtime control is deliberately smaller than the
    # legal full-point candidate retained for actual optimizer reachability.
    full_points = available_talent_points(60, bonus_talent_points=0)
    assert sum(row["witness"].values()) < full_points
    assert sum(row["search_witness"].values()) == full_points
    assert row["witness"]["gift_of_nature"] == 2
    assert row["search_witness"]["gift_of_nature"] == 2

    # No rank disappears from the canonical P2 denominator to obtain GREEN.
    assert (report["pass_count"] + report["fail_count"]
            + report["unresolved_count"] + report["unreachable_count"]
            == report["source_rank_total"] == 103)
