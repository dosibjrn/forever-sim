"""Warlock L20 P3 uses native source/equipment scoring, never the naked IR proxy."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from tools import wf_gate_p3_live as p3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))
from native_p3_equipped import compare_equipped_native  # noqa: E402


def source(*, actor="ClassWarlock", level=20):
    return {
        "raid": {"parties": [{"players": [{
            "class": actor, "level": level,
            "equipment": {"items": [{"id": 100 + i} for i in range(14)]},
            "rotation": {"type": "TypeAPL", "priorityList": []},
        }]}]},
        "encounter": {"duration": 120, "targets": []},
        "simOptions": {"iterations": 5, "randomSeed": "42"},
    }


def prepared(*_args, **_kwargs):
    return {"status": "PREPARED", "actor_class": "ClassWarlock",
            "actor_level": 20, "engine_revision": "pinned-test-engine"}


def paid_receipt(*, actor="ClassWarlock", level=20):
    return {
        "status": "PAID_NATIVE_DIFFERENCE", "objective": "DPS",
        "paid_attempts": 2, "actor_checkpoint_verified": True,
        "native_prepared_actor": {
            "actor_class": actor, "actor_level": level,
            "engine_revision": "pinned-test-engine"},
        "source_occupied_slots": ["head"],
        "evaluations": [
            {"status": "VALID", "score": 7.0, "request_sha256": "original"},
            {"status": "VALID", "score": 7.5, "request_sha256": "changed"}],
        "native_slot_evaluations": [{
            "swap": {"slot": "head", "to_id": 900}, "status": "VALID",
            "score": 7.5, "delta_dps": 0.5, "delta_score": 0.5}],
        "native_slots_valid": 1,
    }


def test_warlock_l20_native_p3_selection_is_specific():
    assert p3.native_item_options_required("warlock", 20, "unrestricted")
    assert not p3.native_item_options_required("warlock", 30, "unrestricted")
    assert not p3.native_item_options_required("warlock", 20, "affliction")


def test_unverified_native_warlock_equipment_refuses_without_ir(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.setattr(p3, "_query_native_unified_p3_items",
                        lambda *_args: {
                            "status": "empty", "items": [],
                            "unverified_candidate_count": 20})
    monkeypatch.setattr(p3, "_paid_native_equipped_probe",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            AssertionError("No native payment for unverified items")))
    result = p3.run_live(ROOT, "warlock", 20)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["NATIVE_ITEM_OPTIONS_PROFICIENCY_UNVERIFIED"]
    assert result["real_source_search_evaluated"] == 0


def test_missing_native_warlock_actor_request_refuses_without_payment(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.delenv("FOREVER_P3_NATIVE_WARLOCK_L20_REQUEST", raising=False)
    monkeypatch.setattr(p3, "_query_native_unified_p3_items",
                        lambda *_args: {"status": "ok", "items": [
                            {"slot": "head", "item_id": 900, "item_level": 20}]})
    monkeypatch.setattr(p3, "_paid_native_equipped_probe",
                        lambda *_a, **_kw: (_ for _ in ()).throw(
                            AssertionError("Cannot pay without pinned L20 actor request")))
    result = p3.run_live(ROOT, "warlock", 20)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["P3_NATIVE_WARLOCK_L20_REQUEST_REQUIRED"]


def test_warlock_native_options_to_equipped_p3_no_python_ir(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.setenv("FOREVER_P3_NATIVE_WARLOCK_L20_REQUEST", "source-L20.json")
    calls = []

    def options(root, binary, cls, level):
        calls.append(("options", binary, cls, level))
        return {"status": "ok", "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
                "source": "source-revision", "items": [
                    {"slot": "head", "item_id": 900, "item_level": 20}]}

    def paid(root, binary, selection, remaining, *, checkpoint):
        calls.append(("paid", binary, selection, remaining, checkpoint))
        return paid_receipt()

    monkeypatch.setattr(p3, "_query_native_unified_p3_items", options)
    monkeypatch.setattr(p3, "_paid_native_equipped_probe", paid)
    result = p3.run_live(ROOT, "warlock", 20)
    assert result["status"] == "PASS", result["reasons"]
    assert result["production_engine"] == "mythicsim_rust"
    assert result["real_source_search_evaluated"] == 0
    assert result["native_equipped_paid_attempts"] == 2
    assert calls == [
        ("options", "selected-engine", "warlock", 20),
        ("paid", "selected-engine",
         {"slots": {"head": {"selected_ids": [900]}}}, 44, "warlock_l20")]


def test_warlock_selected_request_is_forwarded_with_explicit_actor_level(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_WARLOCK_L20_REQUEST", "exact-warlock-L20.json")
    commands = []

    def fake_native(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_native)
    receipt = p3._paid_native_equipped_probe(
        ROOT, "selected-engine",
        {"slots": {"head": {"selected_ids": [900]}}}, 44,
        checkpoint="warlock_l20")
    assert receipt["paid_attempts"] == 2
    command, kw = commands[0]
    assert command[command.index("--request") + 1] == "exact-warlock-L20.json"
    assert command[-4:] == ["--class-key", "warlock", "--level", "20"]
    assert json.loads(kw["input"]) == {"head": {"selected_ids": [900]}}


def test_native_warlock_balanced_dps_pays_real_changed_item_only():
    original = source()
    unchanged = copy.deepcopy(original)
    paid = []

    def evaluator(binary, request, iterations, seed, mode, deadline, **kwargs):
        assert binary == "selected-engine"
        assert mode == "balanced"
        assert kwargs["objective"] == "DPS"
        paid.append(copy.deepcopy(request))
        head = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"]
        return (7.5 if head == 900 else 7.0), {}, 0.01, f"paid-{len(paid)}"

    result = compare_equipped_native(
        "selected-engine", original, {"head": {"selected_ids": [900]}},
        class_key="warlock", level=20, objective="DPS",
        evaluator=evaluator, preparer=prepared)
    assert result["status"] == "PAID_NATIVE_DIFFERENCE"
    assert result["paid_attempts"] == len(paid) == 2
    assert result["actor_checkpoint_verified"]
    assert result["comparison"]["delta_dps"] == 0.5
    assert original == unchanged


def test_native_warlock_cannot_promote_level60_donor_or_wrong_class():
    for fixture in (source(level=60), source(actor="ClassMage")):
        called = []
        result = compare_equipped_native(
            "selected-engine", fixture, {"head": {"selected_ids": [900]}},
            class_key="warlock", level=20, objective="DPS",
            evaluator=lambda *_a, **_kw: called.append(True),
            preparer=prepared)
        assert result["paid_attempts"] == 0
        assert not called

    wrong_native = p3._native_rogue_p3_verdict(
        {"status": "ok", "items": [{"slot": "head", "item_id": 900, "item_level": 20}]},
        paid_receipt(actor="ClassMage"), checkpoint="warlock_l20")
    assert wrong_native["status"] == "FAIL"
    assert any("P3_NATIVE_EQUIPPED_SCORE_UNVERIFIED" in reason
               for reason in wrong_native["reasons"])
