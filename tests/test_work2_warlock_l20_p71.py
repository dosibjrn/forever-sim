"""Warlock L20 P7.1 source-native reference/dispatcher regressions.

Mock native transport only; these tests never count as M1 PASS evidence.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p7_1_live as gate
from tools import wf_p7_native_reference as reference


def _source(root: Path) -> Path:
    path = root / "fixtures/warlock-l20-p71.request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "level": 20,
            "rotation": {"type": "TypeAPL", "priorityList": []},
            "equipment": {"items": []}, "talentsString": "0-0-0"
        }]}]},
        "encounter": {"duration": 120, "targets": [
            {"level": 20, "minBaseDamage": 0, "stats": [0] * 38}
        ]},
        "simOptions": {"iterations": 1000, "randomSeed": "42"},
    }))
    return path


def _native(monkeypatch, *, native_level=20, refused=False):
    binary = Path("/selected/engine/target/release/forever-engine")
    revision = "a" * 40
    paid = []

    def prepare(_binary, path, level):
        assert _binary == binary and level == 20
        if refused:
            return {"status": "REFUSED", "code": "NATIVE_UNSUPPORTED",
                    "reason": "selected source actor unsupported"}
        return {"status": "PREPARED", "class": "ClassWarlock", "level": native_level}

    def score(_binary, path, iterations, *, rng_mode, actor_level):
        assert (_binary, iterations, rng_mode, actor_level) == (
            binary, 1000, "stochastic", 20)
        paid.append(path.read_bytes())
        return {"native_dps": 15.75, "iterations": 1000, "native_rules": "forever",
                "first_duration_s": 120.0}

    monkeypatch.setattr(reference, "_binary_and_pin", lambda root: (binary, revision))
    monkeypatch.setattr(reference, "_prepare_actor", prepare)
    monkeypatch.setattr(reference, "_native",
                        lambda root: SimpleNamespace(native_source_control=score))
    return paid, revision


def test_warlock_native_stochastic_reference_paid_once_and_reused(monkeypatch, tmp_path):
    source = _source(tmp_path)
    paid, revision = _native(monkeypatch)
    result = reference.produce_and_verify_reference(
        tmp_path, "warlock", 20, "unrestricted")
    assert result["status"] == "PASS"  # mocked transport, never M1 credit
    assert result["generation"]["selected_engine_revision"] == revision
    assert result["verification"]["reused_authentic_native_reference_receipt"] is True
    assert result["verification"]["iterations"] == 1000
    assert result["verification"]["reference_configuration_source"] == (
        "native_generated_msim_reference")
    assert paid == [source.read_bytes()]
    assert gate.run_live(tmp_path, "warlock", 20)["status"] == "PASS"
    assert paid == [source.read_bytes()]  # exact sample reused, no second draw


def test_warlock_native_refusal_and_level_mismatch_do_not_pay(monkeypatch, tmp_path):
    _source(tmp_path)
    paid, _ = _native(monkeypatch, refused=True)
    result = reference.produce_reference(tmp_path, "warlock", 20, "unrestricted")
    assert result["reasons"] == ["P7_1_NATIVE_PREPARE_REFUSED"]
    assert result["native_refusal"]["code"] == "NATIVE_UNSUPPORTED"
    assert not paid
    paid, _ = _native(monkeypatch, native_level=60)
    result = reference.produce_reference(tmp_path, "warlock", 20, "unrestricted")
    assert result["reasons"] == ["P7_1_NATIVE_PREPARED_ACTOR_LEVEL_MISMATCH"]
    assert not paid


def test_p71_dispatch_rejects_other_warlock_checkpoints(monkeypatch, tmp_path):
    calls = []

    def forward(root, cls, level, spec):
        calls.append((cls, level, spec))
        return {"status": "BLOCKED", "reasons": [
            "P7_1_NATIVE_GENERATED_REFERENCE_NOT_PINNED"]}

    monkeypatch.setattr(reference, "run_generated_p71", forward)
    assert gate.run_live(tmp_path, "warlock", 20)["reasons"] == [
        "P7_1_NATIVE_GENERATED_REFERENCE_NOT_PINNED"]
    assert calls == [("warlock", 20, "unrestricted")]
    assert gate.run_live(tmp_path, "warlock", 30)["reasons"] == [
        "P7_1_SAVED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]
    assert gate.run_live(tmp_path, "warlock", 20, spec="affliction")["reasons"] == [
        "P7_1_SAVED_REFERENCE_NOT_SELECTED_FOR_CHECKPOINT"]
    assert len(calls) == 1


def test_stationary_fixture_preserves_frozen_reference_scenario():
    """Check our retained P7.1 input, not a moving Rust-fork fixture path.

    Exact request-byte and original-paid-engine provenance are checked in
    test_paid_stochastic_warlock_reference_is_frozen_to_exact_source below.
    The currently selected Rust fork no longer carries the historical
    `warlock-l20-troll-source-equipped.request.json` fixture. Requiring it
    would reject unrelated source-native PRs before their actual tests run.
    """
    root = Path(__file__).resolve().parents[1]
    frozen = json.loads(
        (root / "fixtures/warlock-l20-p71.request.json").read_text())
    player = frozen["raid"]["parties"][0]["players"][0]
    assert player["class"] == "ClassWarlock"
    assert player["race"] == "RaceTroll"
    assert player["equipment"]["items"]
    target = frozen["encounter"]["targets"]
    assert frozen["encounter"]["duration"] == 120
    assert len(target) == 1 and target[0]["level"] == 20
    assert target[0]["minBaseDamage"] == 0 and target[0]["canCrush"] is False
    assert frozen["simOptions"]["iterations"] == 1000


def test_paid_stochastic_warlock_reference_is_frozen_to_exact_source():
    """Receipt provenance, not a second engine correctness or gameplay test."""
    import hashlib

    root = Path(__file__).resolve().parents[1]
    frozen = reference._reference_directory(root, "warlock", 20, "unrestricted")
    raw = (frozen / "request.json").read_bytes()
    fixture = (root / "fixtures/warlock-l20-p71.request.json").read_bytes()
    receipt = json.loads((frozen / "reference.json").read_text())
    encounter = json.loads(raw)["encounter"]
    canonical_encounter = json.dumps(
        encounter, sort_keys=True, separators=(",", ":")).encode()
    assert raw == fixture
    assert receipt["source_request_raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert receipt["encounter_sha256"] == hashlib.sha256(canonical_encounter).hexdigest()
    assert receipt["selected_engine_revision"] == (
        "201e9052ffe4349cad2cca241fc164737ac5a12b")
    assert receipt["native_prepared_actor"] == {
        "status": "PREPARED", "class": "ClassWarlock", "level": 20}
    assert receipt["reference_rng_mode"] == "stochastic"
    assert receipt["reference_iterations"] == 1000
    assert receipt["reference_native_sample"]["iterations"] == 1000
    assert receipt["reference_native_sample"]["native_dps"] == receipt["reference_dps"]
