"""Mage L60 selected-native P3 transport, refusals and equipment regressions."""
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


def _mage_reference():
    # The selected Mage Arcane fixture has 15 equipment entries and no level
    # hint. Only native prepare is authoritative for the actual level.
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassMage", "talentsString": "source-profile",
            "equipment": {"items": [{"id": 100 + index} for index in range(15)]},
            "rotation": {"type": "TypeAPL", "priorityList": []},
        }]}]},
        "encounter": {"duration": 30},
        "simOptions": {"iterations": 5, "randomSeed": "42"},
    }


def _unified_payload(*, item_eligible=True):
    rows = [
        {"item_id": 900, "eligibility": "native_eligible",
         "native": {"item_id": 900, "slot": "weapon", "item_level": 60},
         "unverified": None},
        {"item_id": 901, "eligibility": "native_eligible",
         "native": {"item_id": 901, "slot": "head", "item_level": 50},
         "unverified": None},
        {"item_id": 902, "eligibility": "proficiency_unverified",
         "native": None, "unverified": {"item_type": "ItemTypeHead"}},
    ]
    return {
        "schema_version": 1, "source_revision": "selected-rust-source",
        "class": "mage", "level": 60, "spells": [],
        "talents": {"status": "ok", "trees": [{}, {}, {}]},
        "coverage": {
            "spell_learnability_complete": False,
            "item_eligibility_complete": item_eligible,
            "talent_prerequisites_complete": True,
            "native_item_status": "partial_level_unknown",
        },
        "items": rows,
    }


def test_unified_mage_options_only_forward_confirmed_native_slot(monkeypatch):
    seen = []

    def fake_cli(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(_unified_payload()), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_cli)
    result = p3._query_native_unified_p3_items(ROOT, "selected-engine", "mage", 60)
    assert seen[0][0] == ["selected-engine", "options", "--class", "mage", "--level", "60"]
    assert result["source"] == "selected-rust-source"
    assert result["coverage"]["item_eligibility_complete"] is False
    assert result["unverified_candidate_count"] == 1
    assert [item["item_id"] for item in result["items"]] == [900, 901]
    assert p3._native_p3_equipped_slot_proposals(result)["slots"] == {
        "weapon": {"selected_ids": [900]},
        "head": {"selected_ids": [901]},
    }


def test_mage_p3_routes_to_unified_native_without_gameir(monkeypatch):
    import src.game.data.forever.registry as registry
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")

    def no_python_ir(**_kwargs):
        raise AssertionError("Mage L60 P3 must not enter Python GameIR")

    monkeypatch.setattr(registry, "build_game_ir_slice", no_python_ir)
    monkeypatch.setattr(p3, "_query_native_unified_p3_items",
                        lambda _root, binary, cls, level: {
                            "source": "selected-rust-source", "status": "ok",
                            "transport": "MYTHICSIM_NATIVE_GET_OPTIONS",
                            "items": [{"slot": "weapon", "item_id": 900,
                                       "item_level": 60}],
                            "unverified_candidate_count": 4,
                        })
    seen = []

    def paid(root, binary, selection, remaining, *, checkpoint):
        seen.append((binary, selection, remaining, checkpoint))
        return {
            "status": "PAID_NATIVE_DIFFERENCE", "paid_attempts": 2,
            "actor_checkpoint_verified": True,
            "native_prepared_actor": {"actor_class": "ClassMage", "actor_level": 60,
                                      "engine_revision": "selected-engine-revision"},
            "evaluations": [
                {"status": "VALID", "score": 100.0, "request_sha256": "baseline-sha"},
                {"status": "VALID", "score": 104.0, "request_sha256": "swapped-sha"},
            ],
            "native_slot_evaluations": [{
                "swap": {"slot": "weapon", "to_id": 900},
                "status": "VALID", "score": 104.0, "delta_dps": 4.0,
            }],
            "native_slots_valid": 1,
        }

    monkeypatch.setattr(p3, "_paid_native_equipped_probe", paid)
    result = p3.run_live(ROOT, "mage", 60, spec="arcane")
    assert seen == [("selected-engine",
                     {"slots": {"weapon": {"selected_ids": [900]}}},
                     44, "mage_l60")]
    assert result["status"] == "PASS"  # Synthetic contract-only receipt, NOT gate evidence.
    assert result["item_options_source"] == "MYTHICSIM_NATIVE_GET_OPTIONS"
    assert result["native_unverified_candidate_count"] == 4


def test_mage_p3_rejects_unknown_native_coverage_before_paid(monkeypatch):
    monkeypatch.setenv("FOREVER_P3_NATIVE_ITEM_OPTIONS_BIN", "selected-engine")
    payload = _unified_payload()
    payload["coverage"]["talent_prerequisites_complete"] = None

    def fake_cli(command, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_cli)
    monkeypatch.setattr(p3, "_paid_native_equipped_probe", lambda *_a, **_kw: (
        (_ for _ in ()).throw(AssertionError("No paid call on invalid source"))))
    result = p3.run_live(ROOT, "mage", 60, spec="arcane")
    assert result["status"] == "BLOCKED"
    assert any("NATIVE_OPTIONS_INVALID_COVERAGE" in reason for reason in result["reasons"])
    assert result["real_source_search_evaluated"] == 0


def test_mage_l60_fifteen_item_source_is_checked_by_native_prepare_and_paid():
    reference = _mage_reference()
    original = copy.deepcopy(reference)
    evaluations = []

    def evaluator(binary, request, iterations, seed, rng_mode, deadline, **kwargs):
        assert rng_mode == "balanced"
        evaluations.append(copy.deepcopy(request))
        item = request["raid"]["parties"][0]["players"][0]["equipment"]["items"][14]["id"]
        return (110.0 if item == 900 else 100.0), {}, 0.01, f"sha-{len(evaluations)}"

    result = compare_equipped_native(
        "selected-engine", reference, {"weapon": {"selected_ids": [900]}},
        class_key="mage", level=60, evaluator=evaluator,
        preparer=lambda *_a: {
            "status": "PREPARED", "actor_class": "ClassMage",
            "actor_level": 60, "engine_revision": "selected-rust-revision",
        })
    assert result["status"] == "PAID_NATIVE_DIFFERENCE"
    assert result["actor_checkpoint_verified"] is True
    assert result["comparison"]["delta_dps"] == 10.0
    assert result["paid_attempts"] == 2
    assert evaluations[0] == reference and reference == original
    assert evaluations[1]["raid"]["parties"][0]["players"][0]["equipment"]["items"][14] == {"id": 900}


def test_mage_l60_refuses_unmatched_native_prepared_actor_without_paid():
    result = compare_equipped_native(
        "selected-engine", _mage_reference(), {"weapon": {"selected_ids": [900]}},
        class_key="mage", level=60,
        preparer=lambda *_a: {
            "status": "PREPARED", "actor_class": "ClassMage",
            "actor_level": 20, "engine_revision": "selected-rust-revision",
        },
        evaluator=lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("Wrong-level actor cannot be paid")),
    )
    assert result["status"] == "NATIVE_ACTOR_CHECKPOINT_MISMATCH"
    assert result["paid_attempts"] == 0
    assert result["actor_checkpoint_verified"] is False
