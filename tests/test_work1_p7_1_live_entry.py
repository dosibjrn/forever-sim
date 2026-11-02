"""Fast fail-closed tests for the direct P7.1 production entry.

No fake Rust binary, mock 2D combat, or substitute P7.1 PASS. The final
1000-stochastic-fight native/world acceptance is deliberately on-demand.
"""
import hashlib
import json

from tools import wf_gate_p7_1_live as gate


def _fixture(root):
    request = root / "docs/evidence/druid-l60-balance/p7.3/saved_728_request.json"
    witness = root / "docs/evidence/wf633/WF633_VALIDATION.json"
    request.parent.mkdir(parents=True)
    witness.parent.mkdir(parents=True)
    request.write_text(json.dumps({
        "raid": {"parties": [{"players": [{"class": "ClassDruid",
                                         "balanceDruid": {},
                                         "distanceFromTarget": 15}]}]},
        "encounter": {"targets": [{"level": 63}]},
        "simOptions": {"iterations": 10000},
    }))
    witness.write_text(json.dumps({"engine_revision": gate.PINNED_RUST,
                                   "iterations": 10000,
                                   "reference_dps": 728.1936126415858}))
    return request


def test_unrelated_checkpoint_cannot_use_balance_reference(tmp_path):
    report = gate.run_live(tmp_path, "hunter", 20, spec="beast-mastery")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_SAVED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]


def test_changed_source_request_blocks_before_binary(tmp_path):
    _fixture(tmp_path)
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_SAVED_REQUEST_CHANGED"]


def test_no_native_binary_never_awards_pass(tmp_path, monkeypatch):
    request = _fixture(tmp_path)
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN",
                       str(tmp_path / "missing-forever-engine"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_PINNED_RUST_BINARY_MISSING"]


def test_source_original_iteration_count_is_provenance_not_10000_requirement(
        tmp_path, monkeypatch):
    request = _fixture(tmp_path)
    payload = json.loads(request.read_text())
    payload["simOptions"]["iterations"] = 5000  # historical report metadata
    request.write_text(json.dumps(payload))
    witness = tmp_path / "docs/evidence/wf633/WF633_VALIDATION.json"
    meta = json.loads(witness.read_text())
    meta["iterations"] = 5000
    witness.write_text(json.dumps(meta))
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN",
                       str(tmp_path / "missing-forever-engine"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    # We reach the real pinned-native preflight: no spurious 10k check, and
    # a missing production binary cannot award a PASS.
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_PINNED_RUST_BINARY_MISSING"]


def test_invalid_bounded_probe_cannot_start_native(tmp_path, monkeypatch):
    request = _fixture(tmp_path)
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    for value in ("0", "1001", "10001", "not-an-integer"):
        monkeypatch.setenv("FOREVER_P7_LIVE_PROBE_ITERATIONS", value)
        report = gate.run_live(tmp_path, "druid", 60, spec="balance")
        assert report["status"] == "BLOCKED"
        assert report["reasons"] == ["P7_1_INVALID_LIVE_PROBE_ITERATIONS"]


def test_bounded_probe_still_requires_real_pinned_native(tmp_path, monkeypatch):
    request = _fixture(tmp_path)
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    monkeypatch.setenv("FOREVER_P7_LIVE_PROBE_ITERATIONS", "3")
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN",
                       str(tmp_path / "missing-forever-engine"))
    report = gate.run_live(tmp_path, "druid", 60, spec="balance")
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == ["P7_1_PINNED_RUST_BINARY_MISSING"]


def test_cli_separates_sample_breadth_from_live_dps_proximity(monkeypatch, capsys):
    # Presentation regression only; exact-source Actions prove real Rust/gsim.
    from tools import wf_gate as cli
    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_1_BOUNDED_DIAGNOSTIC_NOT_FULL_SAVED_REFERENCE"],
        "production_engine": "pinned_mythicsim_rust_gsim_2d",
        "source_request_raw_sha256": "reproducible-source-request-hash",
        "native_source_revision": gate.PINNED_RUST,
        "source_report_url": "https://api.mythicsim.com/report",
        "world_damage_events": 430, "world_boundaries": 792,
        "world_dps": 692.1030471575785,
        "saved_reference_dps": 728.1936126415858,
        "behavior_probes_executed": 3,
        "sampled_source_fights": 3, "saved_source_iterations": 10000,
    })
    assert cli.main(["--class", "druid", "--level", "60", "--spec", "balance",
                     "--gate", "P7.1"]) == 1
    report = json.loads(capsys.readouterr().out)
    row = report["results"][0]
    assert report["status"] == row["status"] == "FAIL"
    for key in ("verified", "applicable", "pass_count", "reachability_count",
                "partial_coverage_percent", "pareto_effort_estimate_percent"):
        assert key not in row
    assert row["sampled_source_fights"] == 3
    assert row["saved_source_iterations"] == 10000
    from tools.wf_gate_coverage import p7_required_dps
    required = p7_required_dps("P7.1", 728.1936126415858)
    assert row["dps_objective_required"] == round(required, 4)
    assert row["dps_objective_proximity_percent"] == round(
        100 * min(1.0, 692.1030471575785 / required), 2)
    assert row["dps_objective_gate_pass"] is False


def test_source_fight_sample_cannot_earn_m1_partial():
    from tools.wf_gate_coverage import measured_live_coverage
    sample = {"status": "FAIL", "pass_count": 3,
              "reachability_count": 10000,
              "behavior_probes_executed": 3}
    assert measured_live_coverage(sample) is None


def test_equal_mean_dps_cannot_hide_wrong_source_encounter_duration():
    # Negative control for the real P7.1 native-vs-ACK-world comparison.
    # These small metric dicts test the assertion, NOT a substitute engine.
    native = {"iterations": 3, "native_dps": 692.1030471575785,
              "first_duration_s": 133.0027}
    live = {"iterations_done": 3, "native_dps": 692.1030471575785,
            "world_mean_dps": 692.1030471575785,
            "sampled_duration_s": 133.0027,
            "native_damage_events": 430, "native_world_ticks": 792,
            "per_iteration": [{"duration_s": 133.0027}] * 3}
    assert gate._source_native_world_parity(native, live, 3) is None
    live["sampled_duration_s"] = 132.0027
    assert gate._source_native_world_parity(native, live, 3) == (
        "P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED")
    live["sampled_duration_s"] = 133.0027
    live["per_iteration"][0] = {"duration_s": 132.0027}
    assert gate._source_native_world_parity(native, live, 3) == (
        "P7_1_NATIVE_WORLD_FIRST_DURATION_DIVERGED")
    live["per_iteration"][0] = {"duration_s": 133.0027}
    live["native_world_ticks"] = 0
    assert gate._source_native_world_parity(native, live, 3) == (
        "P7_1_NATIVE_WORLD_EXECUTION_INCOMPLETE")


def test_dps_floor_failure_is_not_mislabeled_as_native_world_parity():
    from tools.wf_gate_coverage import p7_final_stochastic_mean_passes
    assert not p7_final_stochastic_mean_passes(
        "P7.1", 700.0, 728.1936126415858,
        iterations=1000, stochastic=True)
    assert gate._source_native_world_parity(
        {"iterations": 1000, "native_dps": 700.0,
         "first_duration_s": 120.0},
        {"iterations_done": 1000, "native_dps": 700.0,
         "world_mean_dps": 700.0, "sampled_duration_s": 120.0,
         "native_damage_events": 1, "native_world_ticks": 1,
         "per_iteration": [{"duration_s": 120.0}] * 1000},
        1000) is None


def test_m1_action_prepares_exact_source_native_p7_without_heavy_opt_in():
    """The Actions wrapper must make the REAL P7 producer runnable.

    A three-fight source-backed diagnostic is not 3/1000 gate completion.
    Full stochastic acceptance remains explicit, and P6/P7.2+ stay heavy.
    """
    from tools.wf_gate import ROOT
    workflow = (ROOT / ".github/workflows/m1-on-demand-record.yml").read_text()
    assert "repository: sage3648/mythicsim-forever-engine" in workflow
    assert gate.PINNED_RUST in workflow
    assert "patch_world_ingress.py upstream" in workflow
    assert "cargo build --release --locked" in workflow
    assert "FOREVER_MYTHICSIM_RUST_BIN:" in workflow
    assert "FOREVER_P7_LIVE_PROBE_ITERATIONS=3" in workflow
    assert '"$gate" != P7.1' in workflow
    assert '"$entry" == *:P7.*' in workflow  # future P7.2-.5 use same native binary
    assert '"$gate" == P6' in workflow
    assert '"$gate" == P7.*' in workflow
