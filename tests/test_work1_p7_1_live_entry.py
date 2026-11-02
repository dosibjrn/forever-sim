"""Fast fail-closed tests for the direct P7.1 production entry.

No fake Rust binary, mock 2D combat, or substitute P7.1 PASS. The full
10k-fight native/world acceptance is deliberately on-demand.
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


def test_invalid_bounded_probe_cannot_start_native(tmp_path, monkeypatch):
    request = _fixture(tmp_path)
    monkeypatch.setattr(gate, "SAVED_BALANCE_RAW_SHA",
                        hashlib.sha256(request.read_bytes()).hexdigest())
    for value in ("0", "10001", "not-an-integer"):
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


def test_cli_keeps_real_partial_scope_provisional(monkeypatch, capsys):
    # Presentation-only contract: never a substitute for the source-Rust run.
    from tools import wf_gate as cli
    monkeypatch.setattr(cli, "_run_live_gate", lambda *args: {
        "status": "FAIL",
        "reasons": ["P7_1_INCOMPLETE_SOURCE_STOCHASTIC_ITERATIONS"],
        "pass_count": 3, "reachability_count": 10000,
        "verified": 3, "applicable": 10000,
        "behavior_probes_executed": 3,
        "coverage_component": "P7.1.3 real source fights",
        "scope_provisional": True, "coverage_scope_complete": False,
    })
    assert cli.main(["--class", "druid", "--level", "60", "--spec", "balance",
                     "--gate", "P7.1"]) == 1
    report = json.loads(capsys.readouterr().out)
    row = report["results"][0]
    assert report["status"] == row["status"] == "FAIL"
    assert row["verified"] == 3 and row["applicable"] == 10000
    assert row["partial_coverage_percent"] == 0.03
    assert row["scope_provisional"] is True
    assert row["coverage_scope_complete"] is False
