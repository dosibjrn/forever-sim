"""Warlock L20 P7.3 frozen-reference/native-talent forwarding regressions.

The mocks prove Forever's candidate serialization and refusal handling only.
They do not certify MythicSim gameplay, native talent legality or M1 PASS.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p7_2_live as reference_route
from tools import wf_gate_p7_3_live as gate
from tools import wf_p7_native_reference as reference


def _base():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "level": 20,
            "talentsString": "0-0-0",
            "equipment": {"items": [{"id": 5210}]},
            "rotation": {"type": "TypeAPL", "priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 1088}}}}
            ]},
        }]}]},
        "encounter": {"duration": 120, "targets": [{"level": 20}]},
        "simOptions": {"iterations": 1000},
    }


def _options(*_args):
    return {"talents": {"trees": [
        {"talents": [{"index": 0}, {"index": 2}]},
        {"talents": [{"index": 0}]},
        {"talents": [{"index": 1}]},
    ]}}


def test_p73_reuses_exact_warlock_reference_without_stochastic_resample(
        monkeypatch, tmp_path):
    frozen = reference._reference_directory(
        tmp_path, "warlock", 20, "unrestricted")
    frozen.mkdir(parents=True)
    base = _base()
    (frozen / "request.json").write_text(json.dumps(base))
    binary = tmp_path / "forever-engine"
    calls = []
    monkeypatch.setattr(
        reference, "run_generated_p71",
        lambda *args: calls.append(args) or {
            "status": "PASS", "saved_reference_dps": 26.17,
            "source_request_raw_sha256": "authentic-raw-sha"})
    monkeypatch.setattr(
        reference, "_binary_and_pin", lambda _root: (binary, "selected-engine"))
    source, meta, selected = reference_route._pinned_source_runtime(
        tmp_path, "warlock", 20, "unrestricted", "P7.3",
        require_world=False)
    assert source == base
    assert meta["reference_dps"] == 26.17
    assert meta["source_request_raw_sha256"] == "authentic-raw-sha"
    assert selected == binary
    assert calls == [(tmp_path, "warlock", 20, "unrestricted")]
    assert reference_route._pinned_source_runtime(
        tmp_path, "warlock", 20, "affliction", "P7.3",
        require_world=False)["status"] == "BLOCKED"


def test_p73_pays_changed_native_talent_with_gear_apl_encounter_fixed(
        monkeypatch, tmp_path):
    base = _base()
    frozen = copy.deepcopy(base)
    binary = tmp_path / "forever-engine"
    paid = []
    queried = []
    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *a, **kw: (
        base, {"reference_dps": 26.17,
               "source_request_raw_sha256": "authentic-raw-sha",
               "selected_engine_revision": "selected-engine",
               "selected_reference_profile": "unrestricted"}, binary))

    def native_options(_binary, cls, level):
        queried.append((_binary, cls, level))
        return _options()

    def native_score(_binary, path, iterations, *, rng_mode, actor_level):
        assert (_binary, iterations, rng_mode, actor_level) == (
            binary, 3, "balanced", 20)
        paid.append(json.loads(path.read_text()))
        return {"native_dps": 28.0, "iterations": 3}

    def module(_path, name):
        if name == "p73_selected_native_options":
            return SimpleNamespace(query_native_options=native_options)
        assert name == "p73_selected_native_scorer"
        return SimpleNamespace(native_source_control=native_score)

    monkeypatch.setattr(gate, "_source_module", module)
    result = gate.run_live(tmp_path, "warlock", 20)
    assert result["status"] == "PASS"  # mocked native transport, NOT gate proof
    assert result["winner_native_dps"] == 28.0
    assert result["native_source_talent_proposals"] == 4
    assert result["source_legal_cold_candidates_paid"] == 1
    assert result["cold_unique_source_requests"] == 1
    assert result["source_original_talents"] == "0-0-0"
    assert result["cold_winner_talents"] == "1-0-0"
    assert result["cold_winner_request"] == paid[0]
    assert queried == [(binary, "warlock", 20)]
    assert len(paid) == 1
    changed = paid[0]
    player = changed["raid"]["parties"][0]["players"][0]
    baseline = frozen["raid"]["parties"][0]["players"][0]
    assert player["equipment"] == baseline["equipment"]
    assert player["rotation"] == baseline["rotation"]
    assert changed["encounter"] == frozen["encounter"]
    assert changed["simOptions"] == frozen["simOptions"]
    assert base == frozen  # immutable saved reference


def test_p73_native_refusal_not_counted_as_paid_candidate(
        monkeypatch, tmp_path):
    base = _base()
    class NativeSourceRefusal(RuntimeError):
        code = "talents"
        reason = "Rust refused source talent allocation"

    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *a, **kw: (
        base, {"reference_dps": 26.17,
               "selected_engine_revision": "selected-engine"},
        tmp_path / "engine"))
    def module(_path, name):
        if name == "p73_selected_native_options":
            return SimpleNamespace(query_native_options=_options)
        return SimpleNamespace(native_source_control=lambda *a, **kw: (
            _ for _ in ()).throw(NativeSourceRefusal()))

    monkeypatch.setattr(gate, "_source_module", module)
    result = gate.run_live(tmp_path, "warlock", 20)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == [
        "P7_3_NATIVE_REFUSED_SAMPLED_TALENT_CHALLENGERS"]
    assert result["source_legal_cold_candidates_paid"] == 0
    assert result["native_invalid_candidates"] == 4
    assert result["native_refusal_samples"][0].startswith(
        "INVALID:NATIVE_TALENTS:")
    assert result["native_execution_errors"] == 0


def test_p73_rejects_missing_source_options_before_paid_score(
        monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *a, **kw: (
        _base(), {"reference_dps": 26.17}, tmp_path / "engine"))
    monkeypatch.setattr(
        gate, "_source_module", lambda path, name: SimpleNamespace(
            query_native_options=lambda *a: (_ for _ in ()).throw(
                ValueError("Rust get_options returned no trees"))))
    result = gate.run_live(tmp_path, "warlock", 20)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["P7_3_NATIVE_TALENT_OPTIONS_UNAVAILABLE"]
    assert "Rust get_options" in result["native_options_error"]


def test_public_p73_receipt_keeps_complete_native_paid_candidate(
        monkeypatch, capsys):
    from tools import wf_gate
    paid = _base()
    paid["raid"]["parties"][0]["players"][0]["talentsString"] = "1-0-0"
    report = {
        "status": "PASS", "reasons": [],
        "runtime_proof": {"executed": True, "engine_revision": "selected-rust",
                          "source_revision": "paid-native-candidate",
                          "run_id": "p73-paid-1"},
        "production_engine": "pinned_mythicsim_rust_native",
        "native_source_revision": "selected-rust",
        "source_request_raw_sha256": "authentic-reference",
        "cold_winner_request_sha256": "paid-native-candidate",
        "source_legal_cold_candidates_paid": 1,
        "winner_native_dps": 28.0,
        "source_original_talents": "0-0-0",
        "cold_winner_talents": "1-0-0",
        "fixed_rotation_and_gear": True,
        "cold_winner_request": paid,
        "native_rules": "forever",
        "reference_profile": "unrestricted",
        "checkpoint_spec": "unrestricted",
    }
    monkeypatch.setattr(wf_gate, "_run_live_gate", lambda *args: report)
    assert wf_gate.main(["--class", "warlock", "--level", "20",
                         "--spec", "unrestricted", "--gate", "P7.3"]) == 0
    row = json.loads(capsys.readouterr().out)["results"][0]
    assert row["status"] == "PASS"  # mock transport, NOT official M1
    assert row["cold_winner_request"] == paid
    assert row["cold_winner_talents"] == "1-0-0"
    assert row["winner_native_dps"] == 28.0
    assert row["native_rules"] == "forever"
    assert row["fixed_rotation_and_gear"] is True
