import copy
import json

import pytest

from tools.wf_warlock_route_guide import build_route_report, main, render_guide


def paid(candidate="A", trial="one"):
    return {
        "id": candidate, "level": 20, "trial": trial,
        "candidate": candidate, "scenario": "native hostile world",
        "targets_requested": 100, "targets_killed": 100,
        "seconds_per_mob": 12.5, "paid_native_recovery": True,
        "native_world_ack": True,
        "run_url": "https://github.com/dosibjrn/forever-sim/actions/runs/1",
    }


def payload(*rows):
    return {"schema_version": 1, "class": "warlock",
            "start_level": 10, "end_level": 60,
            "observations": list(rows)}


def test_sparse_measured_segment_has_no_fake_talent_route_or_dual_spec():
    report = build_route_report(payload(paid()))
    assert report["measured_levels"] == [20]
    assert len(report["unmeasured_levels"]) == 50
    assert report["elapsed_10_60_seconds"] is None
    assert report["dual_spec"]["time_saved_seconds"] is None
    assert report["full_10_60_native_replay_executed"] is False
    assert report["levels"][10]["status"] == "measured_native_chain"
    assert all(not row["route_step_selected"] for row in report["levels"])
    guide = render_guide(report)
    assert "L10-19, L21-60" in guide
    assert "not measured" in guide.lower()


@pytest.mark.parametrize("change", [
    {"targets_killed": 99}, {"paid_native_recovery": False},
    {"native_world_ack": False}, {"seconds_per_mob": float("nan")},
    {"seconds_per_mob": -1}, {"run_url": ""},
])
def test_unpaid_incomplete_unlinked_or_unscored_never_published(change):
    row = {**paid(), **change}
    with pytest.raises(ValueError):
        build_route_report(payload(row))


def test_trial_comparison_not_allowed_across_scenarios_and_runs():
    a, b = paid("A"), paid("B")
    b["scenario"] = "different"
    with pytest.raises(ValueError, match="different levels or scenarios"):
        build_route_report(payload(a, b))
    b["trial"] = "second-run"
    report = build_route_report(payload(a, b))
    assert len(report["comparisons"]) == 2
    assert all(not trial["comparable_with_other_trials"] for trial in report["comparisons"])


def test_published_cli_fixture_is_measured_only_at_l20(tmp_path):
    from tools.wf_warlock_route_guide import DEFAULT_OBSERVATIONS
    out = tmp_path / "route"
    assert main(["--observations", str(DEFAULT_OBSERVATIONS), "--out", str(out)]) == 0
    report = json.loads((out / "route.json").read_text())
    assert report["measured_levels"] == [20]
    assert len(report["observations"]) == 4
    assert [trial["fastest_observed_seconds_per_mob"] for trial in report["comparisons"]] == [22.679, 18.95]
    assert "300-second finalist" in (out / "GUIDE.md").read_text()
    assert "No contiguous source-native" in (out / "GUIDE.md").read_text()
