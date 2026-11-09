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


def native_cold_summary():
    import hashlib
    source = {"raid": {"parties": [{"players": [{
        "talentsString": "1-0-0",
        "equipment": {"items": [{"id": 101}]},
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": {"spellId": 686}}}}]},
        "warlockOptions": {"summon": 2},
    }]}]}}
    candidate = {"source": source, "recovery": {"health_threshold": 0.5, "mana_threshold": 0.1}}
    candidate_sha = hashlib.sha256(json.dumps(
        candidate, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    source_sha = hashlib.sha256((json.dumps(source, sort_keys=True) + "\n").encode()).hexdigest()
    binary_sha = "a" * 64
    def finalist(seconds):
        receipt = {
            "status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
            "target_count_requested": 100,
            "world_targets_killed": 100,
            "native_actor_continuity_receipt_complete": True,
            "native_recovery_clock_accounted": True,
            "native_2d_paid_objective_eligible": True,
            "native_recovery_mode": "decisions_food_water",
            "native_binary_sha256": binary_sha,
            "original_source_sha256": source_sha,
            "seconds_per_mob": seconds,
        }
        return {"status": receipt["status"], "seconds_per_mob": seconds,
                "candidate_sha256": candidate_sha, "native_receipt": receipt}
    snapshot = {"candidate_sha256": candidate_sha, "candidate": candidate}
    return {
        "kind": "warlock_l20_cold_native_world_candidate_search",
        "finalist_targets": 100, "source_revision": "native-test-pin",
        "engine_binary_sha256": binary_sha,
        "snapshot_30": snapshot, "final_300": snapshot,
        "finalists": {"30s": finalist(22.679), "300s": finalist(24.069)},
    }


def test_actual_cold_receipt_import_retains_native_build_and_policy(tmp_path):
    from tools.wf_warlock_route_guide import observations_from_cold_summary
    native = native_cold_summary()
    rows = observations_from_cold_summary(
        native, run_url="https://github.com/dosibjrn/forever-sim/actions/runs/11",
        trial="native-test")
    assert [r["seconds_per_mob"] for r in rows] == [22.679, 24.069]
    assert rows[0]["talents"] == "1-0-0"
    assert rows[0]["gear"] == [{"id": 101}]
    assert rows[0]["apl"][0]["action"]["castSpell"]["spellId"]["spellId"] == 686
    assert rows[0]["pet"] == {"summon": 2}
    assert rows[0]["recovery_policy"]["mana_threshold"] == 0.1
    manifest = tmp_path / "native.json"
    manifest.write_text(json.dumps(native))
    out = tmp_path / "guide"
    assert main(["--cold-summary", str(manifest), "--run-url",
                 "https://github.com/dosibjrn/forever-sim/actions/runs/11",
                 "--out", str(out)]) == 0
    assert json.loads((out / "route.json").read_text())["measured_levels"] == [20]
    assert "1-0-0" in (out / "GUIDE.md").read_text()


def test_native_cold_receipt_missing_paid_continuity_cannot_be_score():
    from tools.wf_warlock_route_guide import observations_from_cold_summary
    native = native_cold_summary()
    native["finalists"]["300s"]["native_receipt"]["native_recovery_clock_accounted"] = False
    with pytest.raises(ValueError, match="complete paid native"):
        observations_from_cold_summary(
            native, run_url="https://github.com/dosibjrn/forever-sim/actions/runs/11",
            trial="native-test")


def test_native_cold_import_never_substitutes_wrong_snapshot_build():
    from tools.wf_warlock_route_guide import observations_from_cold_summary
    native = native_cold_summary()
    native["snapshot_30"] = {"candidate_sha256": "b" * 64, "candidate": {
        "source": {"raid": {"parties": [{"players": [{"talentsString": "FAKE"}]}]}}
    }}
    rows = observations_from_cold_summary(
        native, run_url="https://github.com/dosibjrn/forever-sim/actions/runs/11",
        trial="native-test")
    assert rows[0]["talents"] is None
    assert rows[1]["talents"] == "1-0-0"
    assert "differs from frozen snapshot" in rows[0]["notes"]


def test_native_cold_request_fingerprint_mismatch_is_rejected():
    from tools.wf_warlock_route_guide import observations_from_cold_summary
    native = native_cold_summary()
    native["finalists"]["30s"]["native_receipt"]["original_source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="does not match native source request"):
        observations_from_cold_summary(
            native, run_url="https://github.com/dosibjrn/forever-sim/actions/runs/11",
            trial="native-test")
