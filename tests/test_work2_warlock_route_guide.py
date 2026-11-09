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



def native_chain_summary(tmp_path, *, level=20):
    """Minimal *producer transport* fixture, not a simulated Warcraft fight."""
    import hashlib
    actor = {
        "talentsString": "1-0-0",
        "equipment": {"items": [{"id": 101}]},
        "rotation": {"priorityList": [{"action": {"castSpell": {"spellId": {"spellId": 686}}}}]},
        "warlockOptions": {"summon": 2},
    }
    source = {"raid": {"parties": [{"players": [actor]}]}}
    candidate_dir = tmp_path / "best_apl"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    request = candidate_dir / "source_request.json"
    request.write_text(json.dumps(source) + "\n")
    sha = hashlib.sha256(request.read_bytes()).hexdigest()
    receipt = {
        "variant": "best_apl",
        "status": "COMPLETED_100_REAL_NATIVE_GSIM_KILLS",
        "killed": 100,
        "target_count_requested": 100,
        "native_binary_sha256": "a" * 64,
        "source_request_sha256": sha,
        "native_actor_continuity_receipt_complete": True,
        "paid_recovery": True,
        "native_recovery_clock_accounted": True,
        "native_recovery_mode": "decisions_food_water",
        "native_2d_paid_objective_eligible": True,
        "world_target_hp_matches_request": True,
        "native_food_water_observed": True,
        "seconds_per_mob": 12.7,
        "mob_hp_native_scenario": 484,
        "scenario_min_base_damage": 20,
        "scenario_swing_speed": 2,
        "recovery_request": {"recovery_policy": "decisions", "health_threshold": 0.5},
        "final_hp": 370,
        "final_mana": 220,
        "native_health_damage": {"observed": True, "damage_taken": 308},
        "native_food_seconds": 125,
        "native_water_seconds": 250,
        "native_food_health_gain": 145.5,
        "native_water_mana_gain": 300.0,
        "native_recovery_seconds": 375.0,
        "walk_paid_s": 257.75,
        "native_damage_events": 24,
    }
    summary = {
        "kind": "real_100_target_source_native_world_attempts",
        "target_count_requested": 100,
        "native_binary_sha256": "a" * 64,
        "native_recovery_requested": {"recovery_policy": "decisions"},
        "results": [receipt],
    }
    if level != 20:
        summary["actor_level"] = level
        receipt["actor_level"] = level
        receipt["native_actor"] = {"level": level, "class": "ClassWarlock"}
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary))
    return path, summary


def test_native_chain_adapter_consumes_exact_source_and_real_paid_receipts(tmp_path):
    from tools.wf_warlock_route_guide import observations_from_native_chain_summary
    path, summary = native_chain_summary(tmp_path)
    rows, refusals = observations_from_native_chain_summary(summary, summary_path=path)
    assert not refusals
    report = build_route_report(payload(*rows))
    assert report["measured_levels"] == [20]
    assert report["full_10_60_native_replay_executed"] is False
    assert rows[0]["gear"] == [{"id": 101}]
    assert rows[0]["pet"] == {"summon": 2}
    assert rows[0]["native_final_hp"] == 370
    assert rows[0]["native_food_seconds"] == 125
    assert rows[0]["native_water_mana_gain"] == 300
    assert rows[0]["native_recovery_seconds"] == 375
    assert rows[0]["native_walk_paid_seconds"] == 257.75
    guide = render_guide(report)
    assert "native_final_hp: 370" in guide
    assert "native_water_seconds: 250" in guide
    assert "native_walk_paid_seconds: 257.75" in guide
    assert "source_request_sha256:" in guide
    assert rows[0]["run_url"] is None
    assert "Local receipt:" in render_guide(report)
    assert "not a claimed executed 10" in render_guide(report)


def test_native_chain_adapter_refuses_unpaid_or_swapped_requests(tmp_path):
    from tools.wf_warlock_route_guide import observations_from_native_chain_summary
    path, summary = native_chain_summary(tmp_path)
    summary["results"][0]["native_recovery_clock_accounted"] = False
    with pytest.raises(ValueError, match="complete paid"):
        observations_from_native_chain_summary(summary, summary_path=path)
    summary["results"][0]["native_recovery_clock_accounted"] = True
    (tmp_path / "best_apl" / "source_request.json").write_text('{"swapped": true}')
    with pytest.raises(ValueError, match="source request bytes differ"):
        observations_from_native_chain_summary(summary, summary_path=path)


def test_native_summary_cli_preserves_real_refusals_and_local_provenance(tmp_path):
    path, summary = native_chain_summary(tmp_path / "input")
    summary["results"].append({
        "variant": "life_tap_40", "status": "INCOMPLETE_OR_NATIVE_REFUSAL",
        "killed": 37, "native_exit_code": 1, "error": "NATIVE_ACTOR_DIED",
    })
    path.write_text(json.dumps(summary))
    out = tmp_path / "report"
    assert main(["--native-summary", str(path), "--out", str(out)]) == 0
    report = json.loads((out / "route.json").read_text())
    assert len(report["observations"]) == 1
    assert report["native_refusals"][0]["killed"] == 37
    guide = (out / "GUIDE.md").read_text()
    assert "NATIVE_ACTOR_DIED" in guide
    assert "Local receipt:" in guide


def test_one_invocation_calls_real_producer_and_publishes_its_saved_summary(tmp_path, monkeypatch):
    from tools import wf_warlock_route_guide as guide
    import subprocess
    binary = tmp_path / "native-engine"
    source = tmp_path / "input.json"
    binary.write_bytes(b"native-binary-placeholder")
    source.write_text("{}")
    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        assert "--targets" in cmd and cmd[cmd.index("--targets") + 1] == "100"
        assert "--hostile-player-tank" in cmd
        assert "--require-native-health-damage" not in cmd
        assert cmd[cmd.index("--recovery-policy") + 1] == "decisions"
        assert cmd[cmd.index("--health-threshold") + 1] == "0.7"
        assert cmd[cmd.index("--mana-threshold") + 1] == "0.25"
        native_chain_summary(tmp_path / "guide" / "native_l20")
        return subprocess.CompletedProcess(cmd, 0, stdout="CHAIN_COMPLETED")

    monkeypatch.setattr(guide.subprocess, "run", fake_run)
    out = tmp_path / "guide"
    assert main(["--execute-native", "--binary", str(binary),
                 "--source", str(source), "--out", str(out)]) == 0
    assert len(commands) == 1
    data = json.loads((out / "route.json").read_text())
    assert data["measured_levels"] == [20]
    assert data["observations"][0]["receipt_path"].endswith("/native_l20/summary.json")
    assert data["observations"][0]["run_url"] is None
    assert data["elapsed_10_60_seconds"] is None


def test_no_paid_native_candidate_cannot_publish_a_measured_route(tmp_path):
    from tools.wf_warlock_route_guide import observations_from_native_chain_summary
    path, summary = native_chain_summary(tmp_path)
    summary["results"][0].update(status="INCOMPLETE_OR_NATIVE_REFUSAL", killed=42, error="NATIVE_ACTOR_DIED")
    rows, refusals = observations_from_native_chain_summary(summary, summary_path=path)
    assert rows == []
    assert refusals[0]["killed"] == 42
    path.write_text(json.dumps(summary))
    out = tmp_path / "guide"
    assert main(["--native-summary", str(path), "--out", str(out)]) == 2
    report = json.loads((out / "route.json").read_text())
    assert report["status"] == "native_refusal_only_no_measured_chain"
    assert report["measured_levels"] == []
    assert len(report["unmeasured_levels"]) == 51
    assert report["observations"] == []
    assert report["native_refusals"][0]["killed"] == 42
    assert "NATIVE_ACTOR_DIED" in (out / "GUIDE.md").read_text()
    assert "L10-60" in (out / "GUIDE.md").read_text()


def test_executed_route_forwards_custom_decisions_thresholds(tmp_path, monkeypatch):
    from tools import wf_warlock_route_guide as guide
    import subprocess
    binary = tmp_path / "engine"
    source = tmp_path / "request.json"
    binary.write_bytes(b"native engine test placeholder")
    source.write_text("{}")
    def fake_run(cmd, **kwargs):
        assert cmd[cmd.index("--health-threshold") + 1] == "0.65"
        assert cmd[cmd.index("--mana-threshold") + 1] == "0.3"
        native_chain_summary(tmp_path / "route" / "native_l20")
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(guide.subprocess, "run", fake_run)
    out = tmp_path / "route"
    assert main(["--execute-native", "--binary", str(binary),
                 "--source", str(source), "--out", str(out),
                 "--health-threshold", "0.65", "--mana-threshold", "0.3"]) == 0
    assert json.loads((out / "route.json").read_text())["measured_levels"] == [20]


def test_zero_incoming_damage_is_observed_not_extra_route_gate(tmp_path):
    from tools.wf_warlock_route_guide import observations_from_native_chain_summary
    path, summary = native_chain_summary(tmp_path)
    summary["results"][0]["native_health_damage"] = {
        "observed": True, "damage_taken": 0, "damage_events": 0}
    summary["results"][0]["native_damage_events"] = 0
    rows, refusals = observations_from_native_chain_summary(summary, summary_path=path)
    assert len(rows) == 1 and not refusals
    assert rows[0]["native_health_damage"]["damage_taken"] == 0
    assert "damage_taken" in render_guide(build_route_report(payload(*rows)))


def test_adjacent_level_native_receipts_are_distinct_and_keep_l20(tmp_path):
    from tools.wf_warlock_route_guide import observations_from_native_chain_summary
    l20, _ = native_chain_summary(tmp_path / "l20")
    l21, summary = native_chain_summary(tmp_path / "l21", level=21)
    rows, refusals = observations_from_native_chain_summary(
        summary, summary_path=l21, trial="real-l21")
    assert not refusals
    assert rows[0]["level"] == 21
    assert "L21" in rows[0]["scenario"]
    out = tmp_path / "route"
    assert main(["--native-summary", str(l20), "--native-summary", str(l21),
                 "--out", str(out)]) == 0
    report = json.loads((out / "route.json").read_text())
    assert report["measured_levels"] == [20, 21]
    assert len(report["comparisons"]) == 2
    assert report["full_10_60_native_replay_executed"] is False
    assert report["elapsed_10_60_seconds"] is None
    assert "L20-21" in (out / "GUIDE.md").read_text()


def test_adjacent_level_cannot_relabel_old_prepared_actor(tmp_path):
    from tools.wf_warlock_route_guide import observations_from_native_chain_summary
    path, summary = native_chain_summary(tmp_path / "l21", level=21)
    summary["results"][0]["native_actor"]["level"] = 20
    with pytest.raises(ValueError, match="Rust-prepared actor"):
        observations_from_native_chain_summary(summary, summary_path=path)
    summary["results"][0]["native_actor"]["level"] = 21
    summary["results"][0]["actor_level"] = 20
    with pytest.raises(ValueError, match="actor-level request"):
        observations_from_native_chain_summary(summary, summary_path=path)


def test_adjacent_failure_keeps_prior_measured_level_and_reports_refusal(tmp_path):
    l20, _ = native_chain_summary(tmp_path / "l20")
    l21, summary = native_chain_summary(tmp_path / "l21", level=21)
    summary["results"][0].update(
        status="INCOMPLETE_OR_NATIVE_REFUSAL", killed=24, error="NATIVE_ACTOR_DIED")
    l21.write_text(json.dumps(summary))
    out = tmp_path / "route"
    assert main(["--native-summary", str(l20), "--native-summary", str(l21),
                 "--out", str(out)]) == 0
    report = json.loads((out / "route.json").read_text())
    assert report["measured_levels"] == [20]
    assert 21 in report["unmeasured_levels"]
    assert report["native_refusals"][0]["level"] == 21
    assert report["native_refusals"][0]["killed"] == 24


def test_adjacent_execute_forwards_level_to_real_native_producer(tmp_path, monkeypatch):
    from tools import wf_warlock_route_guide as guide
    import subprocess
    binary = tmp_path / "engine"
    source = tmp_path / "request.json"
    binary.write_bytes(b"binary-placeholder")
    source.write_text("{}")
    def fake_run(cmd, **kwargs):
        assert cmd[cmd.index("--actor-level") + 1] == "21"
        assert cmd[cmd.index("--targets") + 1] == "100"
        native_chain_summary(tmp_path / "route" / "native_l21", level=21)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(guide.subprocess, "run", fake_run)
    out = tmp_path / "route"
    assert main(["--execute-native", "--binary", str(binary), "--source", str(source),
                 "--actor-level", "21", "--out", str(out)]) == 0
    report = json.loads((out / "route.json").read_text())
    assert report["measured_levels"] == [21]
    assert 20 in report["unmeasured_levels"]
