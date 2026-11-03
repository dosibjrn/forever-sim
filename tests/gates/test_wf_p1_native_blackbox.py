"""P1 source inventory and native single-action request contracts.

Unit tests here validate Forever request plumbing only. Actual native combat
and the live 2D world bridge are exercised by the pinned-Rust integration
test in integrations/mythicsim-rust/tests/test_native_p1_effect_probe.py.
"""
from copy import deepcopy
from pathlib import Path

import pytest

from tools.p1_native_source_inventory import inventory
from tools.wf_p1_native_effects import native_single_action_pair, run_native

ROOT = Path(__file__).resolve().parents[2]


def _sample_request():
    return {
        "raid": {"parties": [{"players": [{
            "class": "Hunter", "talentsString": "123",
            "equipment": {"items": [{"id": 42}]},
            "rotation": {"priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": 14282}}}},
                {"action": {"castSpell": {"spellId": {"spellId": 13550}}}},
            ]},
        }]}]},
        "simOptions": {"iterations": 1, "randomSeed": "43123"},
        "encounter": {"duration": 12},
    }


def _druid_request():
    request = _sample_request()
    request["raid"]["parties"][0]["players"][0]["class"] = "ClassDruid"
    return request


def _scope():
    return {
        "class": "hunter", "level": 20,
        "scenario": "current_solo_leveling_100mob_v1",
        "source_only": True, "game_ir_required": False,
        "candidates": [{"spell_id": 13550}],
        "separate": [{"spell_id": 14282, "status": "NOT_A_PROVEN_CASTABLE_ACTION"}],
    }


def test_hunter_l20_source_inventory_no_gameir_and_no_false_pass():
    result = inventory("hunter", 20)
    assert result["source_only"] is True
    assert result["game_ir_required"] is False
    assert result["effects_tested"] == 0
    assert result["p1_certified"] is False
    assert result["candidate_count"] > 0
    special = {x["spell_id"]: x["status"] for x in result["separate"]}
    assert special[75] == "NATIVE_AUTO_ATTACK"
    assert {14282, 13550} <= {x["spell_id"] for x in result["candidates"]}


@pytest.mark.parametrize("cls", ("druid", "hunter", "mage", "paladin", "priest",
                                  "rogue", "shaman", "warlock", "warrior"))
@pytest.mark.parametrize("level", (20, 60))
def test_class_level_p1_source_inventory_does_not_require_old_python_adapters(cls, level):
    result = inventory(cls, level)
    assert result["class"] == cls
    assert result["level"] == level
    assert result["candidate_count"] + result["separate_count"] > 0
    assert result["p1_certified"] is False


def test_native_single_action_pair_keeps_every_non_action_field_identical():
    request = _sample_request()
    reference = deepcopy(request)
    positive, no_action = native_single_action_pair(request, 14282)

    assert request == reference
    positive_player = positive["raid"]["parties"][0]["players"][0]
    control_player = no_action["raid"]["parties"][0]["players"][0]
    assert positive_player["rotation"]["priorityList"] == [
        {"action": {"castSpell": {"spellId": {"spellId": 14282}}}}
    ]
    assert control_player["rotation"]["priorityList"] == []

    positive_normalized = deepcopy(positive)
    control_normalized = deepcopy(no_action)
    positive_normalized["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"] = ["ACTION"]
    control_normalized["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"] = ["ACTION"]
    assert positive_normalized == control_normalized


def test_native_single_action_pair_rejects_missing_or_ambiguous_action():
    with pytest.raises(ValueError, match="NOT_UNIQUE_IN_APL"):
        native_single_action_pair(_sample_request(), 1130)

    duplicate = _sample_request()
    duplicate["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"].append(
        deepcopy(duplicate["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"][0])
    )
    with pytest.raises(ValueError, match="NOT_UNIQUE_IN_APL"):
        native_single_action_pair(duplicate, 14282)


def test_native_single_action_pair_rejects_hidden_rotation_channels():
    request = _sample_request()
    request["raid"]["parties"][0]["players"][0]["rotation"]["prepullActions"] = [
        {"action": {"castSpell": {"spellId": {"spellId": 1}}}}
    ]
    with pytest.raises(ValueError, match="UNCONTROLLED_ROTATION_CHANNEL"):
        native_single_action_pair(request, 14282)


def test_source_inventory_is_not_a_native_eligibility_veto(monkeypatch, tmp_path):
    """An uncertain source role annotates progress only; native still receives the request."""
    from tools import wf_p1_native_effects as native

    source = _scope()
    monkeypatch.setattr(native, "inventory", lambda *args, **kwargs: source)
    calls = []

    def fake_probe(**kwargs):
        calls.append(kwargs)
        return {
            "status": "NATIVE_DIRECT_BEHAVIOR_VERIFIED",
            "proof_kind": "NATIVE_DIRECT_EFFECT",
            "executor": "msim-rust",
            "native_executed": True,
            "effect_observed": True,
            "controlled_behavior_assertion_passed": True,
            "observable_effects": {"dps_delta": 4.0, "actual_2d_ack": True},
            "p1_certified": False,
        }

    monkeypatch.setattr(native, "run_native_p1_direct_effect_probe", fake_probe)
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"unit-test-placeholder-not-an-engine")
    result = native.run_native(
        binary, _sample_request(), class_key="hunter", level=20, spell_id=14282
    )

    assert len(calls) == 1
    assert calls[0]["spell_id"] == 14282
    assert result["status"] == "NATIVE_DIRECT_BEHAVIOR_VERIFIED"
    assert result["source_candidate_membership"] is False
    assert result["source_scope_membership"] is True
    assert result["p1_native_progress"]["verified"] == 0
    assert result["p1_native_progress"]["diagnostic_only_spell_ids"] == [14282]
    assert result["p1_certified"] is False


def test_source_inventory_failure_does_not_block_native_execution(monkeypatch, tmp_path):
    from tools import wf_p1_native_effects as native

    calls = []

    def fake_probe(**kwargs):
        calls.append(kwargs)
        return {
            "status": "NATIVE_DIRECT_BEHAVIOR_VERIFIED",
            "proof_kind": "NATIVE_DIRECT_EFFECT",
            "executor": "msim-rust",
            "native_executed": True,
            "effect_observed": True,
            "controlled_behavior_assertion_passed": True,
            "observable_effects": {"dps_delta": 2.0, "actual_2d_ack": True},
            "p1_certified": False,
        }

    monkeypatch.setattr(native, "run_native_p1_direct_effect_probe", fake_probe)
    monkeypatch.setattr(
        native, "inventory",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("diagnostic DB unavailable")),
    )
    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"unit-test-placeholder-not-an-engine")
    result = native.run_native(
        binary, _sample_request(), class_key="hunter", level=20, spell_id=14282
    )

    assert len(calls) == 1
    assert result["status"] == "NATIVE_DIRECT_BEHAVIOR_VERIFIED"
    assert "diagnostic DB unavailable" in result["p1_native_progress_error"]


def test_native_prepare_refusal_is_preserved_without_fallback(monkeypatch, tmp_path):
    from src.engine_client import native_p1_effect_probe as probe

    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    binary = engine_root / "forever-engine"
    binary.write_bytes(b"placeholder")
    calls = []

    def prepare(**kwargs):
        calls.append(kwargs["scenario"])
        if kwargs["scenario"].endswith("with-action"):
            return {"status": "UNSUPPORTED", "stage": "prepare",
                    "reason": "native_action_not_supported"}
        return {
            "status": "PREPARED", "stage": "prepare",
            "engine_identity": "selected-pin",
            "request_sha256": "c" * 64,
            "prepared": {"request_sha256": "c" * 64},
        }

    monkeypatch.setattr(probe, "prepare_native_request", prepare)
    monkeypatch.setattr(
        probe, "_simulate_prepared",
        lambda **kwargs: pytest.fail("native prepare refusal must not fall back to simulation"),
    )
    monkeypatch.setattr(
        probe, "_run_world_bridge",
        lambda *args, **kwargs: pytest.fail("native prepare refusal must not reach the world bridge"),
    )
    result = probe.run_native_p1_direct_effect_probe(
        binary=binary, engine_root=engine_root, request=_druid_request(),
        spell_id=14282, timeout_seconds=5,
    )
    assert result["status"] == "UNSUPPORTED"
    assert result["reason"] == "native_action_not_supported"
    assert calls == [
        "p1-druid-l60-single-action-14282-with-action",
        "p1-druid-l60-single-action-14282-no-action",
    ]
    assert result["p1_certified"] is False


def test_native_direct_effect_requires_positive_delta_and_real_world_ack(monkeypatch, tmp_path):
    from src.engine_client import native_p1_effect_probe as probe

    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    binary = engine_root / "forever-engine"
    binary.write_bytes(b"placeholder")
    prepare_count = 0

    def prepare(**kwargs):
        nonlocal prepare_count
        prepare_count += 1
        marker = "with" if kwargs["scenario"].endswith("with-action") else "without"
        digest = ("a" if marker == "with" else "b") * 64
        return {
            "status": "PREPARED", "stage": "prepare",
            "engine_identity": "selected-pin",
            "request_sha256": digest,
            "prepared_sha256": digest,
            "prepared": {"marker": marker, "request_sha256": digest},
        }

    def simulate(**kwargs):
        marker = kwargs["prepared"]["marker"]
        return {
            "status": "EXECUTED", "stage": "sim",
            "dps": 18.0 if marker == "with" else 4.0,
            "engine_identity": "selected-pin",
        }

    world_calls = []
    def world(**kwargs):
        world_calls.append(kwargs)
        return {
            "actual_2d_ack": True,
            "continuous_native_actor": True,
            "world_targets_killed": 2,
            "native_damage_events": 2,
            "checkpoint_certified": False,
            "world_elapsed_seconds": 3.0,
        }

    monkeypatch.setattr(probe, "prepare_native_request", prepare)
    monkeypatch.setattr(probe, "_simulate_prepared", simulate)
    monkeypatch.setattr(probe, "_run_world_bridge", world)
    result = probe.run_native_p1_direct_effect_probe(
        binary=binary, engine_root=engine_root, request=_druid_request(),
        spell_id=14282, timeout_seconds=5, iterations=1,
    )
    assert prepare_count == 2
    assert len(world_calls) == 1
    assert result["status"] == "NATIVE_DIRECT_BEHAVIOR_VERIFIED"
    assert result["dps_delta"] == 14.0
    assert result["positive_action_count"] == 1
    assert result["control_action_count"] == 0
    assert result["effect_observed"] is True
    assert result["controlled_behavior_assertion_passed"] is True
    assert result["observable_effects"]["actual_2d_ack"] is True
    assert result["world_bridge"]["checkpoint_certified"] is False
    assert result["p1_certified"] is False


def test_native_direct_effect_does_not_claim_success_without_metric_delta(monkeypatch, tmp_path):
    from src.engine_client import native_p1_effect_probe as probe

    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    binary = engine_root / "forever-engine"
    binary.write_bytes(b"placeholder")

    def prepare(**kwargs):
        marker = "with" if kwargs["scenario"].endswith("with-action") else "without"
        digest = ("a" if marker == "with" else "b") * 64
        return {
            "status": "PREPARED", "stage": "prepare",
            "engine_identity": "selected-pin",
            "request_sha256": digest,
            "prepared": {"marker": marker, "request_sha256": digest},
        }

    def simulate(**kwargs):
        return {"status": "EXECUTED", "stage": "sim", "dps": 4.0}

    monkeypatch.setattr(probe, "prepare_native_request", prepare)
    monkeypatch.setattr(probe, "_simulate_prepared", simulate)
    monkeypatch.setattr(
        probe, "_run_world_bridge",
        lambda *args, **kwargs: pytest.fail("world bridge must not run without an effect delta"),
    )
    result = probe.run_native_p1_direct_effect_probe(
        binary=binary, engine_root=engine_root, request=_druid_request(),
        spell_id=14282, timeout_seconds=5, iterations=1,
    )
    assert result["status"] == "NO_DIRECT_EFFECT_OBSERVED"
    assert result["effect_observed"] is False
    assert result["p1_certified"] is False


def test_source_only_nonimpact_never_becomes_an_effect_pass():
    result = inventory("druid", 20)
    rows = {x["name"]: x["status"] for x in result["separate"]}
    for name in ("Aquatic Form", "Growl", "Cure Poison", "Rebirth", "Revive"):
        assert rows[name] == "NOT_RELEVANT_TO_SIMULATION"
    assert result["p1_certified"] is False
