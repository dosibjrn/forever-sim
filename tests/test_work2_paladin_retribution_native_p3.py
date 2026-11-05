"""Paladin Retribution L60 selected-native P3 transport (not game-rule validation)."""
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
    # Actual pinned Paladin Retribution source has fourteen equipped entries
    # and no player.level. The prepared native actor, not this hint, decides.
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassPaladin", "talentsString": "legacy-source",
            "equipment": {"items": [{"id": 100 + i} for i in range(14)]},
            "rotation": {"type": "TypeAPL", "priorityList": []},
        }]}]},
        "encounter": {"duration": 120, "targets": []},
        "simOptions": {"iterations": 5, "randomSeed": "42"},
    }


def _prepared(*_args, **_kwargs):
    return {"status": "PREPARED", "actor_class": "ClassPaladin",
            "actor_level": 60, "engine_revision": "selected-test-pin"}


def test_paladin_l60_14_entry_native_request_pays_only_a_source_supplied_swap():
    source = _source()
    frozen = copy.deepcopy(source)
    paid = []

    def native_evaluator(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        assert binary == "selected-engine"
        assert rng_mode == "balanced"
        assert kwargs["objective"] == "DPS"
        paid.append(copy.deepcopy(request))
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][0]["id"]
        return (105.0 if item == 900 else 100.0), {}, 0.02, f"native-paid-{len(paid)}"

    receipt = compare_equipped_native(
        "selected-engine", source, {"head": {"selected_ids": [900]}},
        class_key="paladin", level=60,
        preparer=_prepared, evaluator=native_evaluator)
    assert source == frozen
    assert len(paid) == receipt["paid_attempts"] == 2
    assert paid[0] == source
    assert paid[1]["raid"]["parties"][0]["players"][0]["equipment"]["items"][0] == {"id": 900}
    assert receipt["status"] == "PAID_NATIVE_DIFFERENCE"
    assert receipt["comparison"]["delta_dps"] == 5.0
    assert receipt["native_prepared_actor"]["actor_class"] == "ClassPaladin"
    assert receipt["actor_checkpoint_verified"] is True
    assert len(receipt["source_occupied_slots"]) == 14
    assert "weapon" not in receipt["source_occupied_slots"]
    assert receipt["promotion"] == "MATCHED_PALADIN_L60_NATIVE_SCORED_DIFFERENCE"


def test_paladin_l60_native_prepare_refusal_and_wrong_actor_never_pay():
    def no_score(*_args, **_kwargs):
        raise AssertionError("Native prepare failure cannot spend paid evaluations")

    for prepared, expected in (
        ({"status": "NATIVE_PREPARE_REFUSED", "reason": "real native refusal"},
         "NATIVE_PREPARE_REFUSED"),
        ({"status": "PREPARED", "actor_class": "ClassMage", "actor_level": 60},
         "NATIVE_ACTOR_CHECKPOINT_MISMATCH"),
    ):
        receipt = compare_equipped_native(
            "selected-engine", _source(), {"head": {"selected_ids": [900]}},
            class_key="paladin", level=60, preparer=lambda *_a, **_kw: prepared,
            evaluator=no_score)
        assert receipt["status"] == expected
        assert receipt["paid_attempts"] == 0
        assert receipt["actor_checkpoint_verified"] is False
        if expected == "NATIVE_PREPARE_REFUSED":
            assert receipt["reason"] == "real native refusal"


def test_paladin_retribution_source_and_current_client_preset_are_pinned(monkeypatch):
    """One exact pinned smoke fixture and already sourced talent preset."""
    kind, relative = SOURCES["paladin/retribution"]
    assert kind == "engine"
    assert relative == (
        "validation/2026-10-06-multi-target-paladin-druid-references/"
        "retribution-paladin-2-targets.request.json")
    assert CURRENT_CLIENT_TALENT_OVERRIDES["paladin/retribution"]["class_name"] == "ClassPaladin"

    commands = []

    def fake_paid(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps({
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
        }), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_paid)
    selection = {"slots": {"head": {"selected_ids": [900]}}}
    report = p3._paid_native_equipped_probe(
        ROOT, "selected-engine", selection, 44,
        checkpoint="paladin_retribution_l60")
    assert report["paid_attempts"] == 2
    command, kwargs = commands[0]
    assert command[command.index("--request") + 1].endswith(relative)
    assert command[-6:] == ["--class-key", "paladin", "--level", "60",
                            "--current-client-profile", "paladin/retribution"]
    assert json.loads(kwargs["input"]) == selection["slots"]


def test_paladin_l60_routes_native_options_and_paid_scorer_not_gameir(monkeypatch):
    import src.game.data.forever.registry as registry

    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    monkeypatch.setattr(registry, "build_game_ir_slice", lambda **_kw: (
        (_ for _ in ()).throw(AssertionError("Paladin P3 cannot enter GameIR"))))
    calls = []

    def native_options(root, binary, cls, level):
        calls.append(("options", binary, cls, level))
        return {"status": "ok", "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
                "source": "native-options-pin",
                "items": [{"slot": "head", "item_id": 900, "item_level": 60}]}

    def paid(root, binary, selection, remaining, *, checkpoint):
        calls.append(("paid", binary, selection, remaining, checkpoint))
        return {
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
            "actor_checkpoint_verified": True,
            "native_prepared_actor": {
                "actor_class": "ClassPaladin", "actor_level": 60,
                "engine_revision": "native-engine-pin",
            },
            "source_occupied_slots": ["head"],
            "evaluations": [
                {"status": "VALID", "score": 100.0, "request_sha256": "native-baseline"},
                {"status": "VALID", "score": 105.0, "request_sha256": "native-swap"},
            ],
            "native_slot_evaluations": [
                {"swap": {"slot": "head", "to_id": 900}, "status": "VALID",
                 "score": 105.0, "delta_dps": 5.0}],
            "native_slots_valid": 1,
        }

    monkeypatch.setattr(p3, "_query_native_unified_p3_items", native_options)
    monkeypatch.setattr(p3, "_paid_native_equipped_probe", paid)
    assert p3.native_item_options_required("paladin", 60, "retribution")
    result = p3.run_live(ROOT, "paladin", 60, spec="retribution")
    assert result["status"] == "PASS", result["reasons"]
    assert result["source_occupied_slots"] == ["head"]
    assert result["reachability_count"] == result["pass_count"] == 1
    assert result["real_source_search_evaluated"] == 0
    assert calls == [
        ("options", "selected-engine", "paladin", 60),
        ("paid", "selected-engine",
         {"slots": {"head": {"selected_ids": [900]}}}, 44,
         "paladin_retribution_l60"),
    ]


def test_paladin_native_receipt_rejects_wrong_actor_or_unscored_slot():
    options = {"status": "ok", "items": [
        {"slot": "head", "item_id": 900, "item_level": 60}],
        "transport": "MYTHICSIM_NATIVE_GET_OPTIONS"}
    receipt = {
        "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
        "actor_checkpoint_verified": True,
        "native_prepared_actor": {
            "actor_class": "ClassMage", "actor_level": 60,
            "engine_revision": "engine"},
        "source_occupied_slots": ["head"],
        "evaluations": [
            {"status": "VALID", "score": 100.0, "request_sha256": "paid-sha"},
            {"status": "VALID", "score": 104.0, "request_sha256": "swapped-sha"}],
        "native_slot_evaluations": [
            {"swap": {"slot": "head", "to_id": 900}, "status": "VALID",
             "score": 104.0, "delta_dps": 4.0}],
        "native_slots_valid": 1,
    }
    wrong = p3._native_rogue_p3_verdict(
        options, receipt, checkpoint="paladin_retribution_l60")
    assert wrong["status"] == "FAIL"
    assert any("P3_NATIVE_EQUIPPED_SCORE_UNVERIFIED" in r
               for r in wrong["reasons"])

    correct = copy.deepcopy(receipt)
    correct["native_prepared_actor"]["actor_class"] = "ClassPaladin"
    correct["native_slot_evaluations"] = []
    unscored = p3._native_rogue_p3_verdict(
        options, correct, checkpoint="paladin_retribution_l60")
    assert unscored["status"] == "FAIL"
    assert "P3_NATIVE_SLOT_UNSCORED:head:NOT_ATTEMPTED" in unscored["reasons"]


def test_paladin_retribution_p3_trusted_dispatch_builds_selected_native_engine():
    workflow = (ROOT / ".github/workflows/m1-on-demand-record.yml").read_text(
        encoding="utf-8")
    p3_section = workflow.split('if [[ "$gate" == P3 ]]; then', 1)[1].split(
        'elif [[ ( "$gate" == P4', 1)[0]
    assert '"$class" == paladin && "$level" == 60 && "$spec" == retribution' in p3_section
    assert "native_options_needed=true" in p3_section
