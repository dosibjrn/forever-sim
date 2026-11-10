"""Druid L30 P7.3: frozen reference, native talent proposals and forwarding.

Only Forever-owned request serialization/receipt mapping are tested here.
MythicSim owns talent legality and DPS; mocked scores are not gate evidence.
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
            "class": "ClassDruid", "level": 30, "talentsString": "0-0-0",
            "equipment": {"items": [{"id": 12345}]},
            "rotation": {"type": "TypeAPL", "priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 8921}}}}
            ]},
        }]}]},
        "encounter": {"duration": 120, "targets": [{"level": 30}]},
        "simOptions": {"iterations": 1000},
    }


def _options(*_args):
    return {"talents": {"trees": [
        {"talents": [{"index": 0}, {"index": 2}]},
        {"talents": [{"index": 0}]},
        {"talents": [{"index": 1}]},
    ]}}


def test_p73_uses_exact_druid_l30_frozen_reference_without_stochastic_replay(
        monkeypatch, tmp_path):
    frozen = reference._reference_directory(tmp_path, "druid", 30, "unrestricted")
    frozen.mkdir(parents=True)
    base = _base()
    (frozen / "request.json").write_text(json.dumps(base))
    binary = tmp_path / "forever-engine"
    observed = []
    monkeypatch.setattr(
        reference, "run_generated_p71",
        lambda *args: observed.append(args) or {
            "status": "PASS", "saved_reference_dps": 8.357414975823593,
            "source_request_raw_sha256": "original-druid-request"})
    monkeypatch.setattr(
        reference, "_binary_and_pin", lambda _root: (binary, "pinned-native"))
    selected, meta, engine = reference_route._pinned_source_runtime(
        tmp_path, "druid", 30, "unrestricted", "P7.3", require_world=False)
    assert selected == base
    assert engine == binary
    assert meta["reference_dps"] == 8.357414975823593
    assert meta["selected_engine_revision"] == "pinned-native"
    assert meta["source_request_raw_sha256"] == "original-druid-request"
    assert observed == [(tmp_path, "druid", 30, "unrestricted")]
    assert reference_route._pinned_source_runtime(
        tmp_path, "druid", 30, "feral", "P7.3",
        require_world=False)["status"] == "BLOCKED"


def test_p73_druid_l30_pays_native_changed_talent_only(
        monkeypatch, tmp_path):
    base = _base()
    frozen = copy.deepcopy(base)
    binary = tmp_path / "forever-engine"
    paid = []
    queried = []
    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *a, **kw: (
        base, {"reference_dps": 8.357414975823593,
               "source_request_raw_sha256": "frozen-native",
               "selected_engine_revision": "pinned-native",
               "selected_reference_profile": "unrestricted"}, binary))

    def query(_binary, class_key, level):
        queried.append((_binary, class_key, level))
        return _options()

    def score(_binary, path, iterations, *, rng_mode, actor_level):
        assert (_binary, iterations, rng_mode, actor_level) == (
            binary, 3, "balanced", 30)
        paid.append(json.loads(path.read_text()))
        return {"iterations": 3, "native_dps": 8.7}

    def source_module(_path, name):
        if name == "p73_selected_native_options":
            return SimpleNamespace(query_native_options=query)
        assert name == "p73_selected_native_scorer"
        return SimpleNamespace(native_source_control=score)

    monkeypatch.setattr(gate, "_source_module", source_module)
    result = gate.run_live(tmp_path, "druid", 30)
    assert result["status"] == "PASS"  # mock forwarding only
    assert queried == [(binary, "druid", 30)]
    assert result["native_source_talent_proposals"] == 4
    assert result["source_legal_cold_candidates_paid"] == 1
    assert result["cold_winner_talents"] == "1-0-0"
    assert result["winner_native_dps"] == 8.7
    assert result["cold_winner_request"] == paid[0]
    assert len(paid) == 1
    assert paid[0]["raid"]["parties"][0]["players"][0]["equipment"] == (
        frozen["raid"]["parties"][0]["players"][0]["equipment"])
    assert paid[0]["raid"]["parties"][0]["players"][0]["rotation"] == (
        frozen["raid"]["parties"][0]["players"][0]["rotation"])
    assert paid[0]["encounter"] == frozen["encounter"]
    assert paid[0]["simOptions"] == frozen["simOptions"]
    assert base == frozen


def test_p73_druid_l30_native_refusal_never_becomes_paid_pass(
        monkeypatch, tmp_path):
    class Refused(RuntimeError):
        code = "talents"
        reason = "native rejected this allocation"

    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *a, **kw: (
        _base(), {"reference_dps": 8.357414975823593},
        tmp_path / "forever-engine"))

    def source_module(_path, name):
        if name == "p73_selected_native_options":
            return SimpleNamespace(query_native_options=_options)
        return SimpleNamespace(native_source_control=lambda *a, **kw: (
            (_ for _ in ()).throw(Refused())))

    monkeypatch.setattr(gate, "_source_module", source_module)
    result = gate.run_live(tmp_path, "druid", 30)
    assert result["status"] == "BLOCKED"
    assert result["source_legal_cold_candidates_paid"] == 0
    assert result["native_invalid_candidates"] == 4
    assert result["native_execution_errors"] == 0


def test_p73_druid_l30_missing_native_options_does_not_pay(
        monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *a, **kw: (
        _base(), {"reference_dps": 8.357414975823593},
        tmp_path / "forever-engine"))
    monkeypatch.setattr(gate, "_source_module", lambda *a, **kw: (
        SimpleNamespace(query_native_options=lambda *a: (
            (_ for _ in ()).throw(ValueError("native options missing"))))))
    result = gate.run_live(tmp_path, "druid", 30)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["P7_3_NATIVE_TALENT_OPTIONS_UNAVAILABLE"]
