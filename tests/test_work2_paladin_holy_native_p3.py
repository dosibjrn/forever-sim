"""Paladin Holy L60: native HPS equipped-P3 transport, not DPS/TPS proxy."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import wf_gate_p3_live as p3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/mythicsim-rust"))
from native_p3_equipped import compare_equipped_native  # noqa: E402
from native_l60_matrix import SOURCES, CURRENT_CLIENT_TALENT_OVERRIDES  # noqa: E402


def source():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassPaladin", "talentsString": "source-legacy",
            "equipment": {"items": [{"id": i + 100} for i in range(14)]},
            "rotation": {"type": "TypeAPL", "priorityList": []},
        }]}]},
        "encounter": {"duration": 180, "targets": []},
        "simOptions": {"iterations": 5, "randomSeed": "42"},
    }


def prepared(*_args, **_kwargs):
    return {"status": "PREPARED", "actor_class": "ClassPaladin",
            "actor_level": 60, "engine_revision": "selected-test-engine"}


def paid_receipt(*, actor="ClassPaladin", objective="HPS", delta=4.0):
    return {
        "status": "PAID_NATIVE_DIFFERENCE", "objective": objective,
        "paid_attempts": 2, "actor_checkpoint_verified": True,
        "native_prepared_actor": {
            "actor_class": actor, "actor_level": 60,
            "engine_revision": "selected-test-engine"},
        "source_occupied_slots": ["head"],
        "evaluations": [
            {"status": "VALID", "score": 100.0, "request_sha256": "baseline"},
            {"status": "VALID", "score": 100.0 + delta, "request_sha256": "changed"}],
        "native_slot_evaluations": [{
            "swap": {"slot": "head", "to_id": 900},
            "status": "VALID", "score": 100.0 + delta,
            "delta_score": delta, "delta_dps": None}],
        "native_slots_valid": 1,
    }


def test_holy_equipped_uses_balanced_hps_and_never_reports_dps():
    fixture = source()
    original = copy.deepcopy(fixture)
    seen = []

    def evaluator(binary, request, iterations, seed, mode, deadline, **kwargs):
        assert binary == "selected-engine"
        assert mode == "balanced"
        assert kwargs["objective"] == "HPS"
        seen.append(copy.deepcopy(request))
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"]
        return (104.0 if item == 900 else 100.0), {}, 0.02, f"paid-{len(seen)}"

    result = compare_equipped_native(
        "selected-engine", fixture, {"head": {"selected_ids": [900]}},
        class_key="paladin", level=60, objective="HPS",
        evaluator=evaluator, preparer=prepared)
    assert result["status"] == "PAID_NATIVE_DIFFERENCE"
    assert result["objective"] == "HPS"
    assert result["paid_attempts"] == len(seen) == 2
    assert result["actor_checkpoint_verified"] is True
    assert result["native_prepared_actor"]["actor_class"] == "ClassPaladin"
    assert len(result["source_occupied_slots"]) == 14
    assert result["comparison"]["objective"] == "HPS"
    assert result["comparison"]["delta_score"] == 4.0
    assert "delta_dps" not in result["comparison"]
    assert result["native_slot_evaluations"][0]["delta_score"] == 4.0
    assert result["native_slot_evaluations"][0]["delta_dps"] is None
    assert fixture == original


def test_holy_prepare_refusal_never_consumes_paid_call():
    def no_score(*_args, **_kwargs):
        raise AssertionError("Refusal must not evaluate")

    result = compare_equipped_native(
        "selected-engine", source(), {"head": {"selected_ids": [900]}},
        class_key="paladin", level=60, objective="HPS",
        evaluator=no_score,
        preparer=lambda *_a, **_kw: {
            "status": "NATIVE_PREPARE_REFUSED", "reason": "native refusal"})
    assert result["status"] == "NATIVE_PREPARE_REFUSED"
    assert result["reason"] == "native refusal"
    assert result["paid_attempts"] == 0


def test_holy_does_not_allow_unknown_objective():
    with pytest.raises(ValueError, match="P3_NATIVE_EQUIPPED_BUDGET_INVALID"):
        compare_equipped_native(
            "selected-engine", source(), {"head": {"selected_ids": [900]}},
            class_key="paladin", level=60, objective="HEALING",
            preparer=prepared)


def test_holy_pinned_request_and_current_client_preset(monkeypatch):
    kind, relative = SOURCES["paladin/holy"]
    assert kind == "engine"
    assert relative == "fixtures/mage/prepared-v2/holy-paladin-healing.request.json"
    preset = CURRENT_CLIENT_TALENT_OVERRIDES["paladin/holy"]
    assert preset["class_name"] == "ClassPaladin"
    assert preset["talents_string"] == "55320015022101251-503020005001"

    calls = []

    def fake_native(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2}), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_native)
    selection = {"slots": {"head": {"selected_ids": [900]}}}
    result = p3._paid_native_equipped_probe(
        ROOT, "selected-engine", selection, 44, checkpoint="paladin_holy_l60")
    assert result["paid_attempts"] == 2
    cmd, kw = calls[0]
    assert cmd[cmd.index("--request") + 1].endswith(relative)
    assert cmd[-6:] == ["--class-key", "paladin", "--level", "60",
                       "--current-client-profile", "paladin/holy"]
    assert json.loads(kw["input"]) == selection["slots"]


def test_holy_native_get_options_and_paid_hps_no_gameir(monkeypatch):
    import src.game.data.forever.registry as registry

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **_kw: (
        (_ for _ in ()).throw(AssertionError("Holy must not use GameIR"))))
    calls = []

    def options(root, binary, cls, level):
        calls.append(("options", binary, cls, level))
        return {"status": "ok", "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
                "source": "native-options", "items": [
                    {"slot": "head", "item_id": 900, "item_level": 60}]}

    def paid(root, binary, selection, remaining, *, checkpoint):
        calls.append(("paid", binary, selection, remaining, checkpoint))
        return paid_receipt()

    monkeypatch.setattr(p3, "_query_native_unified_p3_items", options)
    monkeypatch.setattr(p3, "_paid_native_equipped_probe", paid)
    assert p3.native_item_options_required("paladin", 60, "holy")
    result = p3.run_live(ROOT, "paladin", 60, spec="holy")
    assert result["status"] == "PASS", result["reasons"]
    assert result["reachability_count"] == result["pass_count"] == 1
    assert result["native_equipped_paid_attempts"] == 2
    assert result["real_source_search_evaluated"] == 0
    assert calls == [
        ("options", "selected-engine", "paladin", 60),
        ("paid", "selected-engine",
         {"slots": {"head": {"selected_ids": [900]}}}, 44,
         "paladin_holy_l60")]


@pytest.mark.parametrize("actor,objective", [
    ("ClassMage", "HPS"), ("ClassPaladin", "DPS"), ("ClassPaladin", "TPS")])
def test_holy_rejects_proxy_actor_and_non_healing_objective(actor, objective):
    options = {"transport": "MYTHICSIM_NATIVE_GET_OPTIONS", "status": "ok",
               "items": [{"slot": "head", "item_id": 900, "item_level": 60}]}
    result = p3._native_rogue_p3_verdict(
        options, paid_receipt(actor=actor, objective=objective),
        checkpoint="paladin_holy_l60")
    assert result["status"] == "FAIL"
    assert ("P3_NATIVE_OBJECTIVE_MISMATCH" in result["reasons"]
            if objective != "HPS" else
            any("P3_NATIVE_EQUIPPED_SCORE_UNVERIFIED" in reason
                for reason in result["reasons"]))


def test_holy_native_zero_sensitivity_is_not_fabricated():
    options = {"transport": "MYTHICSIM_NATIVE_GET_OPTIONS", "status": "ok",
               "items": [{"slot": "head", "item_id": 900, "item_level": 60}]}
    result = p3._native_rogue_p3_verdict(
        options, paid_receipt(delta=0.0), checkpoint="paladin_holy_l60")
    assert result["status"] == "FAIL"
    assert "P3_NATIVE_RELEVANT_SCORE_SENSITIVITY_NOT_MEASURED" in result["reasons"]


def test_holy_official_dispatch_builds_selected_native_options():
    workflow = (ROOT / ".github/workflows/m1-on-demand-record.yml").read_text(
        encoding="utf-8")
    p3_section = workflow.split('if [[ "$gate" == P3 ]]; then', 1)[1].split(
        'elif [[ ( "$gate" == P4', 1)[0]
    assert '"$spec" == protection || "$spec" == holy' in p3_section
    assert "native_options_needed=true" in p3_section

def test_native_relic_options_reach_pinned_holy_ranged_request_position():
    # Source get_options returns relic items, while the selected full-equipped
    # native request serializes the same position as ranged (slot index 16).
    source_options = {"items": [
        {"slot": "relic", "item_id": 272436, "item_level": 60},
        {"slot": "relic", "item_id": 272437, "item_level": 60},
    ]}
    selected = p3._native_p3_equipped_slot_proposals(source_options)["slots"]
    assert selected["ranged"]["selected_ids"] == [272436, 272437]
    from native_p3_equipped import first_equipped_proposal
    fixture = source()
    fixture["raid"]["parties"][0]["players"][0]["equipment"]["items"].extend(
        [{"id": 500}, {"id": 501}, {"id": 272436}])
    modified, swap = first_equipped_proposal(
        fixture, selected, expected_class="ClassPaladin")
    assert swap["slot"] == "ranged"
    assert swap["slot_index"] == 16
    assert swap["from_id"] == 272436
    assert swap["to_id"] == 272437
    assert modified["raid"]["parties"][0]["players"][0]["equipment"]["items"][16]["id"] == 272437
    assert fixture["raid"]["parties"][0]["players"][0]["equipment"]["items"][16]["id"] == 272436
