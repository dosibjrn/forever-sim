"""Paladin Protection L60: Forever-owned native P3 routing and TPS receipt."""
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
from native_l60_matrix import SOURCES, CURRENT_CLIENT_TALENT_OVERRIDES  # noqa: E402


def _source():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassPaladin", "talentsString": "source-legacy",
            "equipment": {"items": [{"id": i + 100} for i in range(14)]},
            "rotation": {"type": "TypeAPL", "priorityList": []},
        }]}]},
        "encounter": {"duration": 120, "targets": []},
        "simOptions": {"iterations": 5, "randomSeed": "42"},
    }


def _prepared(*_args, **_kwargs):
    return {"status": "PREPARED", "actor_class": "ClassPaladin",
            "actor_level": 60, "engine_revision": "selected-test-engine"}


def _paid_receipt(*, actor_class="ClassPaladin", objective="TPS"):
    return {
        "status": "PAID_NATIVE_DIFFERENCE", "objective": objective,
        "paid_attempts": 2, "actor_checkpoint_verified": True,
        "native_prepared_actor": {
            "actor_class": actor_class, "actor_level": 60,
            "engine_revision": "selected-test-engine",
        },
        "source_occupied_slots": ["head"],
        "evaluations": [
            {"status": "VALID", "score": 100.0, "request_sha256": "baseline"},
            {"status": "VALID", "score": 104.0, "request_sha256": "changed"},
        ],
        "native_slot_evaluations": [{
            "swap": {"slot": "head", "to_id": 900},
            "status": "VALID", "score": 104.0, "delta_score": 4.0,
            "delta_dps": None,
        }],
        "native_slots_valid": 1,
    }


def test_protection_native_paid_equipment_uses_balanced_tps_not_dps():
    source = _source()
    frozen = copy.deepcopy(source)
    paid = []

    def evaluator(binary, request, iterations, seed, mode, deadline, **kwargs):
        assert binary == "selected-engine"
        assert mode == "balanced"
        assert kwargs["objective"] == "TPS"
        paid.append(copy.deepcopy(request))
        head = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"]
        return (104.0 if head == 900 else 100.0), {}, 0.02, f"native-{len(paid)}"

    result = compare_equipped_native(
        "selected-engine", source, {"head": {"selected_ids": [900]}},
        class_key="paladin", level=60, objective="TPS",
        preparer=_prepared, evaluator=evaluator)
    assert result["status"] == "PAID_NATIVE_DIFFERENCE"
    assert result["objective"] == "TPS"
    assert result["actor_checkpoint_verified"] is True
    assert result["native_prepared_actor"]["actor_class"] == "ClassPaladin"
    assert len(result["source_occupied_slots"]) == 14
    assert result["paid_attempts"] == len(paid) == 2
    assert result["comparison"]["delta_score"] == 4.0
    assert "delta_dps" not in result["comparison"]
    assert result["native_slot_evaluations"][0]["delta_score"] == 4.0
    assert result["native_slot_evaluations"][0]["delta_dps"] is None
    assert source == frozen


def test_protection_native_refusal_never_pays():
    def no_score(*_args, **_kwargs):
        raise AssertionError("Native prepare refusal must not pay")

    result = compare_equipped_native(
        "selected-engine", _source(), {"head": {"selected_ids": [900]}},
        class_key="paladin", level=60, objective="TPS",
        preparer=lambda *_a, **_kw: {
            "status": "NATIVE_PREPARE_REFUSED", "reason": "native refusal"},
        evaluator=no_score)
    assert result["status"] == "NATIVE_PREPARE_REFUSED"
    assert result["reason"] == "native refusal"
    assert result["paid_attempts"] == 0


def test_protection_pinned_fixture_and_preset_forwarded_unchanged(monkeypatch):
    kind, relative = SOURCES["paladin/protection"]
    assert kind == "engine"
    assert relative == (
        "validation/2026-10-06-multi-target-paladin-druid-references/"
        "protection-paladin-2-targets.request.json")
    preset = CURRENT_CLIENT_TALENT_OVERRIDES["paladin/protection"]
    assert preset["class_name"] == "ClassPaladin"
    assert preset["talents_string"] == "050050002-05302102213301531-502"

    calls = []

    def fake_native(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
        }), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_native)
    selection = {"slots": {"head": {"selected_ids": [900]}}}
    report = p3._paid_native_equipped_probe(
        ROOT, "selected-engine", selection, 44,
        checkpoint="paladin_protection_l60")
    assert report["paid_attempts"] == 2
    cmd, kw = calls[0]
    assert cmd[cmd.index("--request") + 1].endswith(relative)
    assert cmd[-6:] == ["--class-key", "paladin", "--level", "60",
                         "--current-client-profile", "paladin/protection"]
    assert json.loads(kw["input"]) == selection["slots"]


def test_protection_p3_uses_selected_native_options_and_tps_receipt(monkeypatch):
    import src.game.data.forever.registry as registry

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **_kw: (
        (_ for _ in ()).throw(AssertionError("No GameIR fallback for Protection"))))
    calls = []

    def options(root, binary, cls, level):
        calls.append(("options", binary, cls, level))
        return {"status": "ok", "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
                "source": "native-options", "items": [
                    {"slot": "head", "item_id": 900, "item_level": 60}]}

    def paid(root, binary, selection, remaining, *, checkpoint):
        calls.append(("paid", binary, selection, remaining, checkpoint))
        return _paid_receipt()

    monkeypatch.setattr(p3, "_query_native_unified_p3_items", options)
    monkeypatch.setattr(p3, "_paid_native_equipped_probe", paid)
    assert p3.native_item_options_required("paladin", 60, "protection")
    result = p3.run_live(ROOT, "paladin", 60, spec="protection")
    assert result["status"] == "PASS", result["reasons"]
    assert result["reachability_count"] == result["pass_count"] == 1
    assert result["native_equipped_paid_attempts"] == 2
    assert result["real_source_search_evaluated"] == 0
    assert calls == [
        ("options", "selected-engine", "paladin", 60),
        ("paid", "selected-engine",
         {"slots": {"head": {"selected_ids": [900]}}}, 44,
         "paladin_protection_l60"),
    ]


def test_protection_wrong_actor_or_dps_objective_cannot_pass():
    options = {"transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
               "status": "ok", "items": [
                   {"slot": "head", "item_id": 900, "item_level": 60}]}
    wrong_actor = p3._native_rogue_p3_verdict(
        options, _paid_receipt(actor_class="ClassMage"),
        checkpoint="paladin_protection_l60")
    assert wrong_actor["status"] == "FAIL"
    assert any("P3_NATIVE_EQUIPPED_SCORE_UNVERIFIED" in reason
               for reason in wrong_actor["reasons"])

    wrong_objective = p3._native_rogue_p3_verdict(
        options, _paid_receipt(objective="DPS"),
        checkpoint="paladin_protection_l60")
    assert wrong_objective["status"] == "FAIL"
    assert "P3_NATIVE_OBJECTIVE_MISMATCH" in wrong_objective["reasons"]


def test_protection_trusted_dispatch_selects_native_engine():
    workflow = (ROOT / ".github/workflows/m1-on-demand-record.yml").read_text(
        encoding="utf-8")
    p3_section = workflow.split('if [[ "$gate" == P3 ]]; then', 1)[1].split(
        'elif [[ ( "$gate" == P4', 1)[0]
    assert '"$spec" == retribution || "$spec" == protection' in p3_section
    assert "native_options_needed=true" in p3_section
