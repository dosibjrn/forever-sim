"""Warlock P7.2: native-only APL proposals from a one-action frozen reference.

Mocks check Forever's source forwarding, not Warcraft legality or M1 evidence.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p7_2_live as gate
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


def test_warlock_p72_uses_paid_frozen_reference_no_stochastic_resample(
        monkeypatch, tmp_path):
    frozen = reference._reference_directory(
        tmp_path, "warlock", 20, "unrestricted")
    frozen.mkdir(parents=True)
    base = _base()
    (frozen / "request.json").write_text(json.dumps(base))
    binary = tmp_path / "forever-engine"
    monkeypatch.setattr(
        reference, "run_generated_p71",
        lambda *a: {"status": "PASS", "saved_reference_dps": 26.17,
                    "source_request_raw_sha256": "frozen-source-sha"})
    monkeypatch.setattr(
        reference, "_binary_and_pin", lambda root: (binary, "selected-engine"))
    original, meta, selected = gate._pinned_source_runtime(
        tmp_path, "warlock", 20, "unrestricted", "P7.2",
        require_world=False)
    assert original == base
    assert selected == binary
    assert meta["reference_dps"] == 26.17
    assert meta["source_request_raw_sha256"] == "frozen-source-sha"
    assert meta["native_actor_level_context"] == 20


def test_warlock_p72_native_spell_challenger_is_paid_and_keeps_fixed_axes(
        monkeypatch, tmp_path):
    base = _base()
    frozen = copy.deepcopy(base)
    binary = tmp_path / "forever-engine"
    paid = []
    fetched = []

    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *a, **kw: (
        base, {"reference_dps": 26.17,
               "source_request_raw_sha256": "frozen-source-sha",
               "selected_engine_revision": "selected-engine",
               "selected_reference_profile": "unrestricted"}, binary))
    monkeypatch.setattr(
        gate, "_cold_apl",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("one-action Warlock cannot use generic mutator")))

    def native_options(_binary, _class, _level):
        fetched.append((_binary, _class, _level))
        return {"spells": [{"spell_id": 1088}, {"spell_id": 172},
                           {"spell_id": 172}, {"spell_id": None}]}

    def native_score(_binary, path, iterations, *, rng_mode, actor_level):
        assert (_binary, iterations, rng_mode, actor_level) == (
            binary, 3, "balanced", 20)
        paid.append(json.loads(path.read_text()))
        return {"native_dps": 29.5, "iterations": 3}

    def module(_path, name):
        if name == "p72_selected_native_options":
            return SimpleNamespace(query_native_options=native_options)
        assert name == "p72_selected_native_scorer"
        return SimpleNamespace(native_source_control=native_score)

    monkeypatch.setattr(gate, "_source_module", module)
    result = gate.run_live(tmp_path, "warlock", 20)
    assert result["status"] == "PASS"  # mocked native transport, not a gate result
    assert result["winner_native_dps"] == 29.5
    assert result["source_legal_cold_candidates_paid"] == 1
    assert result["search_rng_mode"] == "balanced"
    assert fetched == [(binary, "warlock", 20)]
    assert len(paid) == 1
    player = paid[0]["raid"]["parties"][0]["players"][0]
    assert player["talentsString"] == frozen["raid"]["parties"][0]["players"][0]["talentsString"]
    assert player["equipment"] == frozen["raid"]["parties"][0]["players"][0]["equipment"]
    assert player["rotation"]["priorityList"] == [
        {"action": {"castSpell": {"spellId": {"spellId": 172}}}},
        {"action": {"castSpell": {"spellId": {"spellId": 1088}}}},
    ]
    assert base == frozen  # no mutation of pinned stochastic reference


def test_warlock_p72_native_refusal_not_paid_pass(monkeypatch, tmp_path):
    base = _base()
    class NativeSourceRefusal(RuntimeError):
        code = "INVALID"
        reason = "native rejected changed APL"

    monkeypatch.setattr(gate, "_pinned_source_runtime", lambda *a, **kw: (
        base, {"reference_dps": 26.17, "selected_engine_revision": "selected"},
        tmp_path / "engine"))
    def module(_path, name):
        if name == "p72_selected_native_options":
            return SimpleNamespace(query_native_options=lambda *a: {
                "spells": [{"spell_id": 172}]})
        return SimpleNamespace(
            native_source_control=lambda *a, **kw: (_ for _ in ()).throw(
                NativeSourceRefusal()),
            NativeSourceRefusal=NativeSourceRefusal)
    monkeypatch.setattr(gate, "_source_module", module)
    report = gate.run_live(tmp_path, "warlock", 20)
    assert report["status"] == "BLOCKED"
    assert report["reasons"] == [
        "P7_2_NATIVE_REFUSED_ALL_DISTINCT_APL_CANDIDATES"]
    assert report["source_legal_cold_candidates_paid"] == 0
    assert report["native_refusals"][0]["code"] == "INVALID"
