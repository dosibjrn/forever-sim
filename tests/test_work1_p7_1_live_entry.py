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
