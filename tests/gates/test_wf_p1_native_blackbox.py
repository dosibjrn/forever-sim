"""Boundary tests for the native P1 PreparedV2 caller.

These tests cover request shaping and fail-closed response propagation only.
They do not mock a native combat PASS; the positive effect path is exercised
against the pinned Rust binary by integrations/mythicsim-rust/tests/.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.engine_client import native_p1_effect_probe as probe
from tools.wf_p1_native_effects import (
    DRUID_CLAW_RANK1,
    build_druid_cat_action_request,
    native_single_action_pair,
    run_native,
)


def _request(spell_id=DRUID_CLAW_RANK1):
    return {
        "raid": {
            "parties": [{
                "players": [{
                    "class": "ClassDruid",
                    "rotation": {
                        "priorityList": [{
                            "action": {
                                "castSpell": {
                                    "spellId": {"spellId": spell_id}
                                }
                            }
                        }]
                    },
                }]
            }]
        },
        "simOptions": {"iterations": 10, "randomSeed": "647003"},
    }


def test_single_action_pair_removes_only_the_selected_priority_row():
    request = _request()
    positive, control = native_single_action_pair(request, DRUID_CLAW_RANK1)
    assert positive == request
    assert control["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"] == []
    assert control["simOptions"] == request["simOptions"]
    assert request["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]


def test_single_action_pair_rejects_duplicate_selected_actions():
    request = _request()
    player = request["raid"]["parties"][0]["players"][0]
    player["rotation"]["priorityList"].append(
        player["rotation"]["priorityList"][0]
    )
    try:
        native_single_action_pair(request, DRUID_CLAW_RANK1)
    except ValueError as exc:
        assert "AMBIGUOUS" in str(exc) or "DUPLICATE" in str(exc)
    else:
        raise AssertionError("duplicate native action was accepted")


def test_druid_cat_request_builder_uses_only_fixture_and_selected_action(tmp_path):
    fixture = tmp_path / "tests" / "classes" / "druid" / "prepare" / "cat.request.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(json.dumps(_request(9830)), encoding="utf-8")
    request = build_druid_cat_action_request(tmp_path, DRUID_CLAW_RANK1)
    player = request["raid"]["parties"][0]["players"][0]
    assert player["class"] == "ClassDruid"
    assert player["rotation"]["priorityList"] == [{
        "action": {"castSpell": {"spellId": {"spellId": DRUID_CLAW_RANK1}}}
    }]


def test_missing_selected_rust_binary_is_blocked_without_fallback(tmp_path):
    engine_root = tmp_path / "integrations" / "mythicsim-rust" / "engine"
    request = _request()
    result = run_native(
        engine_root / "target" / "debug" / "forever-engine",
        request,
        class_key="druid",
        level=20,
        spell_id=DRUID_CLAW_RANK1,
        root=tmp_path,
        world_required=False,
    )
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SELECTED_RUST_BINARY_MISSING"
    assert result["native_executed"] is False
    assert result["effect_observed"] is False
    assert result["p1_certified"] is False


def test_native_prepare_refusal_is_preserved_and_never_simulated(tmp_path, monkeypatch):
    engine_root = tmp_path / "integrations" / "mythicsim-rust" / "engine"
    binary = engine_root / "target" / "debug" / "forever-engine"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"test-only executable placeholder")
    calls = []

    def prepare_native_request(*, binary, request, scenario, deadline):
        calls.append(scenario)
        if scenario.endswith("with-action"):
            return {
                "status": "UNSUPPORTED",
                "reason": "selected native engine does not support this request",
                "engine_identity": "test-native-identity",
            }
        return {
            "status": "PREPARED",
            "prepared": {"scenario": scenario},
            "engine_identity": "test-native-identity",
        }

    def forbidden_simulation(*_args, **_kwargs):
        raise AssertionError("native prepare refusal must stop before simulation")

    monkeypatch.setattr(probe, "prepare_native_request", prepare_native_request)
    monkeypatch.setattr(probe, "_simulate_prepared", forbidden_simulation)
    result = run_native(
        binary,
        _request(),
        class_key="druid",
        level=20,
        spell_id=DRUID_CLAW_RANK1,
        root=tmp_path,
        world_required=False,
    )
    assert result["status"] == "UNSUPPORTED"
    assert result["reason"] == "selected native engine does not support this request"
    assert result["native_executed"] is False
    assert result["effect_observed"] is False
    assert result["p1_certified"] is False
    assert len(calls) == 2
