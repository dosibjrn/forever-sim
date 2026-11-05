"""Native reference route: forwarding and fail-closed identity, not fake gate evidence."""
import hashlib
import json
from types import SimpleNamespace
from tools import wf_gate_p7_1_live as p71
from tools import wf_p7_native_reference as native


def _frozen(root):
    folder = root / native.BASE
    folder.mkdir(parents=True)
    doc = {"raid": {"parties": [{"players": [{"class": "ClassDruid"}]}]},
           "encounter": {"targets": [{"level": 23}]},
           "simOptions": {"iterations": 1000}}
    raw = json.dumps(doc, sort_keys=True).encode()
    (folder / native.REQUEST).write_bytes(raw)
    witness = {
        "source": "native_generated_msim_reference",
        "selected_engine_revision": "selected-sha",
        "source_request_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "native_prepared_request_sha256": "a" * 64,
        "native_prepared_actor_class": "ClassDruid",
        "native_prepared_actor_level": 20,
        "native_rules": "forever", "target_level": 23,
        "encounter_sha256": native.digest(json.dumps(
            doc["encounter"], sort_keys=True, separators=(",", ":")).encode()),
        "rng_mode": "stochastic", "iterations": 1000, "reference_dps": 42.0,
        "native_receipt": {"iterations": 1000, "native_dps": 42.0},
    }
    (folder / native.RECEIPT).write_text(json.dumps(witness))
    return folder, witness


def test_route_is_specific_to_druid_l20(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(native, "run_native_generated_p71",
                        lambda root, spec: calls.append((root, spec)) or {
                            "status": "BLOCKED", "reasons": ["not paid"]})
    result = p71.run_live(tmp_path, "druid", 20, spec="unrestricted")
    assert result["status"] == "BLOCKED"
    assert calls == [(tmp_path, "unrestricted")]


def test_missing_receipt_never_runs_sample(tmp_path, monkeypatch):
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    monkeypatch.setattr(native, "selected_pin", lambda *_: "selected-sha")
    assert p71.run_live(tmp_path, "druid", 20)["reasons"] == [
        "P7_1_NATIVE_GENERATED_REFERENCE_NOT_CAPTURED"]


def test_pinned_capture_runs_native_1000_stochastic(tmp_path, monkeypatch):
    folder, witness = _frozen(tmp_path)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    monkeypatch.setattr(native, "selected_pin", lambda *_: "selected-sha")
    monkeypatch.setattr(native, "native_prepared_actor", lambda *_: "a" * 64)
    observed = []
    def score(binary, request, iterations, *, rng_mode):
        observed.append((request, iterations, rng_mode))
        return {"iterations": 1000, "native_dps": 42.0}
    monkeypatch.setattr(native, "native_module",
                        lambda *_: SimpleNamespace(native_source_control=score))
    result = p71.run_live(tmp_path, "druid", 20)
    assert result["status"] == "PASS"
    assert result["reference_configuration_source"] == "native_generated_msim_reference"
    assert observed == [(folder / native.REQUEST, 1000, "stochastic")]
    witness["selected_engine_revision"] = "different"
    (folder / native.RECEIPT).write_text(json.dumps(witness))
    assert p71.run_live(tmp_path, "druid", 20)["reasons"] == [
        "P7_1_NATIVE_GENERATED_REFERENCE_RECEIPT_MISMATCH"]


def test_native_reports_actual_l60_actor_as_refusal(tmp_path, monkeypatch):
    _frozen(tmp_path)
    binary = tmp_path / "upstream/target/release/forever-engine"
    binary.parent.mkdir(parents=True)
    binary.touch()
    monkeypatch.setenv("FOREVER_MYTHICSIM_RUST_BIN", str(binary))
    monkeypatch.setattr(native, "selected_pin", lambda *_: "selected-sha")
    def reject(*_):
        raise ValueError("P7_1_NATIVE_ACTOR_LEVEL_MISMATCH:('ClassDruid', 60)")
    monkeypatch.setattr(native, "native_prepared_actor", reject)
    result = p71.run_live(tmp_path, "druid", 20)
    assert result["status"] == "BLOCKED"
    assert "'ClassDruid', 60" in result["native_execution_error"]
