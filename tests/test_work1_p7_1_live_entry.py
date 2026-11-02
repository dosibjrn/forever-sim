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
    assert row["dps_objective_proximity_percent"] == 95.04
    assert row["dps_objective_gate_pass"] is False


def test_source_fight_sample_cannot_earn_m1_partial():
    from tools.wf_gate_coverage import measured_live_coverage
    sample = {"status": "FAIL", "pass_count": 3,
              "reachability_count": 10000,
              "behavior_probes_executed": 3}
    assert measured_live_coverage(sample) is None
