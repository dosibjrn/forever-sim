"""P1 Forever native request/response boundary contracts.

Unit tests validate Forever-owned request plumbing and response handling only.
The pinned-Rust integration separately exercises the real native call and
live 2D world bridge.
"""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time

import pytest

from src.engine_client.native_p2_rank_probe import (
    NativeRngMode,
    _simulate_prepared,
)

from tools.wf_p1_native_effects import native_single_action_pair, run_native



def _simulate_prepared_report(monkeypatch, tmp_path, report, *, allow_zero):
    """Exercise the actual Forever report adapter with a synthetic native CLI reply.

    The fake executable only writes the supplied response envelope; it does
    not assert or emulate MythicSim's Warcraft mechanics.
    """
    from src.engine_client import native_p2_rank_probe as adapter

    def fake_run(argv, **kwargs):
        output = Path(argv[argv.index("--outfile") + 1])
        output.write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    return _simulate_prepared(
        binary_path=tmp_path / "forever-engine",
        prepared={"sim": {"iterations": 10, "seed": 647003}},
        rng_mode=NativeRngMode.BALANCED,
        iterations=10,
        seed=647003,
        deadline=time.monotonic() + 5,
        allow_zero_dps_if_avg_absent=allow_zero,
    )


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



def test_prepare_native_request_forwards_non_druid_candidate_to_selected_engine(
    monkeypatch, tmp_path
):
    from src.engine_client import native_p2_rank_probe as adapter

    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"placeholder")
    request = _sample_request()
    original = deepcopy(request)
    captured = {}

    def fake_run(argv, **kwargs):
        request_path = Path(argv[argv.index("--request") + 1])
        prepared_path = Path(argv[argv.index("--outfile") + 1])
        captured["request"] = json.loads(request_path.read_text(encoding="utf-8"))
        prepared_path.write_text(json.dumps({
            "schema_version": 2,
            "contract": "forever-prepared",
            "reference": {"engine_revision": "selected-pin"},
            "player": {"talents_string": "123", "talents": {}},
        }), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    result = adapter.prepare_native_request(
        binary=binary,
        request=request,
        scenario="p1-hunter-single-action-14282",
        deadline=time.monotonic() + 5,
    )

    assert request == original
    assert captured["request"]["raid"]["parties"][0]["players"][0]["class"] == "Hunter"
    assert captured["request"]["simOptions"]["debugFirstIteration"] is False
    assert result["status"] == "PREPARED"
    assert result["engine_identity"] == "selected-pin"


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        ("talents", "INVALID"),
        ("rotation_unsupported", "UNSUPPORTED"),
        ("prepare_fault", "ERROR"),
    ],
)
def test_prepare_native_request_preserves_non_druid_native_refusal(
    monkeypatch, tmp_path, code, expected_status
):
    from src.engine_client import native_p2_rank_probe as adapter

    binary = tmp_path / "forever-engine"
    binary.write_bytes(b"placeholder")

    def fake_run(argv, **kwargs):
        refusal = {"prepared": False, "refusal": {
            "code": code, "reason": "native refusal reason",
        }}
        return subprocess.CompletedProcess(
            argv, 1, stdout=json.dumps(refusal), stderr=""
        )

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    result = adapter.prepare_native_request(
        binary=binary,
        request=_sample_request(),
        scenario="p1-hunter-single-action-14282",
        deadline=time.monotonic() + 5,
    )

    assert result["status"] == expected_status
    assert result["reason"] == "native refusal reason"
    assert result["refusal"]["code"] == code


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


def test_native_single_action_pair_forwards_absent_candidate_as_native_wire_request():
    request = _sample_request()
    reference = deepcopy(request)
    positive, no_action = native_single_action_pair(request, 1130)

    positive_player = positive["raid"]["parties"][0]["players"][0]
    control_player = no_action["raid"]["parties"][0]["players"][0]
    assert positive_player["rotation"]["priorityList"] == [
        {"action": {"castSpell": {"spellId": {"spellId": 1130}}}}
    ]
    assert control_player["rotation"]["priorityList"] == []
    assert request == reference

    positive_normalized = deepcopy(positive)
    control_normalized = deepcopy(no_action)
    positive_normalized["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"] = ["ACTION"]
    control_normalized["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"] = ["ACTION"]
    assert positive_normalized == control_normalized


def test_native_single_action_pair_rejects_ambiguous_duplicate_action():
    duplicate = _sample_request()
    duplicate["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"].append(
        deepcopy(duplicate["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"][0])
    )
    with pytest.raises(ValueError, match="AMBIGUOUS_IN_APL"):
        native_single_action_pair(duplicate, 14282)


def test_native_single_action_pair_rejects_hidden_rotation_channels():
    request = _sample_request()
    request["raid"]["parties"][0]["players"][0]["rotation"]["prepullActions"] = [
        {"action": {"castSpell": {"spellId": {"spellId": 1}}}}
    ]
    with pytest.raises(ValueError, match="UNCONTROLLED_ROTATION_CHANNEL"):
        native_single_action_pair(request, 14282)


def test_native_probe_has_no_source_inventory_or_shadow_progress_dependency(
    monkeypatch, tmp_path
):
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
            "observable_effects": {"dps_delta": 4.0, "actual_2d_ack": True},
            "p1_certified": False,
        }

    monkeypatch.setattr(native, "run_native_p1_direct_effect_probe", fake_probe)
    result = native.run_native(
        tmp_path / "forever-engine",
        _sample_request(),
        class_key="hunter",
        level=20,
        spell_id=14282,
    )

    assert len(calls) == 1
    assert calls[0]["spell_id"] == 14282
    assert result["status"] == "NATIVE_DIRECT_BEHAVIOR_VERIFIED"
    assert result["native_executed"] is True
    assert result["p1_certified"] is False
    assert not hasattr(native, "inventory")
    assert not hasattr(native, "native_p1_progress")
    assert "source_candidate_membership" not in result
    assert "source_scope_membership" not in result
    assert "p1_native_progress" not in result
    assert "p1_native_progress_error" not in result


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
            player = kwargs["request"]["raid"]["parties"][0]["players"][0]
            assert player["rotation"]["priorityList"] == [
                {"action": {"castSpell": {"spellId": {"spellId": 1130}}}}
            ]
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
        binary=binary, engine_root=engine_root, request=_sample_request(),
        spell_id=1130, timeout_seconds=5,
    )
    assert result["status"] == "UNSUPPORTED"
    assert result["reason"] == "native_action_not_supported"
    # A non-Druid candidate reaches native; its refusal is final. Do not
    # prepare a redundant no-action control or execute either side.
    assert calls == ["p1-hunter-single-action-1130-with-action"]
    assert result["p1_certified"] is False


@pytest.mark.parametrize("native_status", ["INVALID", "UNSUPPORTED", "ERROR"])
def test_native_positive_sim_refusal_skips_control_and_world(
    monkeypatch, tmp_path, native_status
):
    """Native sim refusals are final; no redundant paid control execution."""
    from src.engine_client import native_p1_effect_probe as probe

    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    binary = engine_root / "forever-engine"
    binary.write_bytes(b"placeholder")
    sim_calls = []

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
        sim_calls.append(kwargs["prepared"]["marker"])
        if kwargs["prepared"]["marker"] != "with":
            pytest.fail("native positive refusal must not run a control sim")
        return {
            "status": native_status, "stage": "sim",
            "reason": "native_owned_sim_refusal",
        }

    monkeypatch.setattr(probe, "prepare_native_request", prepare)
    monkeypatch.setattr(probe, "_simulate_prepared", simulate)
    monkeypatch.setattr(
        probe, "_run_world_bridge",
        lambda *args, **kwargs: pytest.fail("native refusal must not reach world"),
    )
    result = probe.run_native_p1_direct_effect_probe(
        binary=binary, engine_root=engine_root, request=_sample_request(),
        spell_id=14282, timeout_seconds=5, iterations=1,
    )
    assert sim_calls == ["with"]
    assert result["status"] == native_status
    assert result["reason"] == "native_owned_sim_refusal"
    assert result["positive_sim"]["status"] == native_status
    assert "control_sim" not in result
    assert result["native_executed"] is False
    assert result["p1_certified"] is False


@pytest.mark.parametrize(
    ("completed_targets", "expected_status"),
    [(100, "NATIVE_DIRECT_BEHAVIOR_VERIFIED"), (99, "ERROR")],
)
def test_native_direct_effect_requires_all_requested_world_targets(
    monkeypatch, tmp_path, completed_targets, expected_status
):
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
    def world(binary_path, prepared, *, target_count, mob_health):
        world_calls.append({
            "binary_path": binary_path,
            "prepared": prepared,
            "target_count": target_count,
            "mob_health": mob_health,
        })
        return {
            "actual_2d_ack": True,
            "continuous_native_actor": True,
            "world_targets_killed": completed_targets,
            "world_kills": [{"target_id": i} for i in range(completed_targets)],
            "native_windows": [{"target_id": i} for i in range(completed_targets)],
            "native_damage_events": completed_targets,
            "checkpoint_certified": False,
            "world_elapsed_seconds": 3.0,
        }

    monkeypatch.setattr(probe, "prepare_native_request", prepare)
    monkeypatch.setattr(probe, "_simulate_prepared", simulate)
    monkeypatch.setattr(probe, "_run_world_bridge", world)
    result = probe.run_native_p1_direct_effect_probe(
        binary=binary, engine_root=engine_root, request=_druid_request(),
        spell_id=14282, timeout_seconds=5, iterations=1, target_count=100,
    )
    assert prepare_count == 2
    assert len(world_calls) == 1
    assert world_calls[0]["target_count"] == 100
    assert result["dps_delta"] == 14.0
    assert result["positive_action_count"] == 1
    assert result["control_action_count"] == 0
    assert result["p1_certified"] is False
    if expected_status == "NATIVE_DIRECT_BEHAVIOR_VERIFIED":
        assert result["status"] == expected_status
        assert result["effect_observed"] is True
        assert result["controlled_behavior_assertion_passed"] is True
        assert result["observable_effects"]["actual_2d_ack"] is True
        assert result["observable_effects"]["world_targets_requested"] == 100
        assert result["observable_effects"]["world_targets_killed"] == 100
        assert result["world_bridge"]["checkpoint_certified"] is False
    else:
        assert result["status"] == "ERROR"
        assert result["reason"] == "NATIVE_P1_WORLD_BRIDGE_CAUSALITY_NOT_CONFIRMED"
        assert result["effect_observed"] is False


def test_native_nonspatial_direct_effect_skips_unneeded_world_bridge(monkeypatch, tmp_path):
    from src.engine_client import native_p1_effect_probe as probe

    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    binary = engine_root / "forever-engine"
    binary.write_bytes(b"placeholder")
    prepared_calls = []
    simulated = []

    def prepare(**kwargs):
        prepared_calls.append(kwargs)
        marker = "with" if kwargs["scenario"].endswith("with-action") else "without"
        digest = ("a" if marker == "with" else "b") * 64
        return {
            "status": "PREPARED", "stage": "prepare",
            "engine_identity": "selected-pin",
            "request_sha256": digest,
            "prepared": {"marker": marker, "request_sha256": digest},
        }

    def simulate(**kwargs):
        marker = kwargs["prepared"]["marker"]
        simulated.append(marker)
        return {
            "status": "EXECUTED", "stage": "sim",
            "dps": 18.0 if marker == "with" else 4.0,
            "engine_identity": "selected-pin",
        }

    monkeypatch.setattr(probe, "prepare_native_request", prepare)
    monkeypatch.setattr(probe, "_simulate_prepared", simulate)
    monkeypatch.setattr(
        probe, "_run_world_bridge",
        lambda *args, **kwargs: pytest.fail("non-spatial direct effect must not start 2D"),
    )
    action_row = {"action": {"castSpell": {"spellId": {"spellId": 14282}}}}
    result = probe.run_native_p1_direct_effect_probe(
        binary=binary, engine_root=engine_root, request=_sample_request(),
        spell_id=14282, action_row=action_row, timeout_seconds=5, iterations=1,
        requires_2d_world=False, target_count=0, world_mob_health=0,
    )

    assert [call["scenario"] for call in prepared_calls] == [
        "p1-hunter-single-action-14282-with-action",
        "p1-hunter-single-action-14282-no-action",
    ]
    assert prepared_calls[0]["request"]["raid"]["parties"][0]["players"][0][
        "rotation"
    ]["priorityList"] == [action_row]
    assert simulated == ["with", "without"]
    assert result["status"] == "NATIVE_DIRECT_EFFECT_VERIFIED"
    assert result["dps_delta"] == 14.0
    assert result["effect_observed"] is True
    assert result["controlled_behavior_assertion_passed"] is True
    assert result["world_bridge_required"] is False
    assert result["world_bridge_status"] == "NOT_REQUIRED_NONSPATIAL_EFFECT"
    assert result["observable_effects"]["dps_delta"] == 14.0
    assert "world_bridge" not in result
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


def test_empty_native_control_report_counts_zero_only_after_all_fights_complete(
    monkeypatch, tmp_path
):
    # Match the real Rust protobuf-JSON shape used by the 2D bridge: dps.avg
    # is omitted for a zero-damage fight, while iterationsDone is explicit.
    report = {
        "identity": {"engine": "forever-engine"},
        "result": {
            "iterationsDone": 10,
            "raidMetrics": {"dps": {}},
        },
    }
    result = _simulate_prepared_report(
        monkeypatch, tmp_path, report, allow_zero=True
    )
    assert result["status"] == "EXECUTED", result
    assert result["dps"] == 0.0
    assert result["iterations_done"] == 10
    assert result["zero_dps_due_to_absent_avg"] is True


def test_empty_native_control_report_remains_invalid_for_default_p2_parser(
    monkeypatch, tmp_path
):
    report = {
        "identity": {"engine": "forever-engine"},
        "result": {
            "iterationsDone": 10,
            "raidMetrics": {"dps": {}},
        },
    }
    result = _simulate_prepared_report(
        monkeypatch, tmp_path, report, allow_zero=False
    )
    assert result["status"] == "ERROR"
    assert result["reason"] == "NATIVE_SIM_REPORT_INVALID:KeyError:'avg'"


def test_empty_native_control_report_is_rejected_when_iterations_are_incomplete(
    monkeypatch, tmp_path
):
    report = {
        "identity": {"engine": "forever-engine"},
        "result": {
            "iterationsDone": 9,
            "raidMetrics": {"dps": {}},
        },
    }
    result = _simulate_prepared_report(
        monkeypatch, tmp_path, report, allow_zero=True
    )
    assert result["status"] == "ERROR"
    assert "NATIVE_SIM_EMPTY_DPS_ITERATIONS_INCOMPLETE" in result["reason"]


def test_empty_native_control_report_does_not_hide_missing_dps_block(
    monkeypatch, tmp_path
):
    report = {
        "identity": {"engine": "forever-engine"},
        "result": {
            "iterationsDone": 10,
            "raidMetrics": {},
        },
    }
    result = _simulate_prepared_report(
        monkeypatch, tmp_path, report, allow_zero=True
    )
    assert result["status"] == "ERROR"
    assert result["reason"] == "NATIVE_SIM_REPORT_INVALID:KeyError:'dps'"


def test_native_prepared_action_inventory_preserves_native_records_without_filtering():
    from src.engine_client.native_p1_effect_probe import native_prepared_action_inventory

    spellbook = [
        {
            "action_id": {"spell_id": 14282},
            "rank": 1,
            "class_spell": "AimedShot",
            "flags": ["APL"],
            "cast_kind": "cast",
        },
        {
            "action_id": {"spell_id": 13550},
            "rank": 2,
            "class_spell": "SerpentSting",
            "flags": ["APL"],
            "cast_kind": "instant",
        },
        {
            "action_id": None,
            "rank": 0,
            "class_spell": "PassiveProc",
            "flags": [],
            "cast_kind": "passive",
        },
    ]
    cooldowns = [{"spell_id": 3045}, {"spell_id": 19503}]
    receipt = {
        "status": "PREPARED",
        "engine_identity": "selected-pin",
        "prepared_sha256": "a" * 64,
        "prepared": {
            "player": {
                "class": "Hunter",
                "level": 20,
                "talents_string": "123",
                "talents": {"beast_mastery": 1},
                "spells": spellbook,
                "major_cooldowns": cooldowns,
            },
        },
    }
    original = deepcopy(receipt)

    result = native_prepared_action_inventory(receipt)

    assert receipt == original
    assert result["status"] == "AVAILABLE"
    assert result["engine_identity"] == "selected-pin"
    assert result["player_class"] == "Hunter"
    assert result["player_level"] == 20
    assert result["spell_count"] == 3
    assert result["spell_records_with_action_id"] == 2
    assert result["major_cooldown_count"] == 2
    assert result["spells"] == spellbook
    assert result["major_cooldowns"] == cooldowns
    assert result["p1_certified"] is False


@pytest.mark.parametrize(
    "prepared",
    [
        {},
        {"player": {}},
        {"player": {"spells": None}},
        {"player": {"spells": [{"action_id": 1}, None]}},
        {"player": {"spells": [], "major_cooldowns": {}}},
    ],
)
def test_native_prepared_action_inventory_fails_closed_when_native_records_are_missing(prepared):
    from src.engine_client.native_p1_effect_probe import native_prepared_action_inventory

    result = native_prepared_action_inventory({
        "status": "PREPARED",
        "engine_identity": "selected-pin",
        "prepared": prepared,
    })

    assert result["status"] == "UNAVAILABLE"
    assert result["p1_certified"] is False


def test_native_direct_effect_report_carries_prepared_action_inventory(monkeypatch, tmp_path):
    from src.engine_client import native_p1_effect_probe as probe

    engine_root = tmp_path / "engine"
    engine_root.mkdir()
    binary = engine_root / "forever-engine"
    binary.write_bytes(b"placeholder")
    spellbook = [
        {
            "action_id": {"spell_id": 14282},
            "rank": 1,
            "class_spell": "AimedShot",
            "flags": ["APL"],
        },
        {
            "action_id": {"spell_id": 13550},
            "rank": 2,
            "class_spell": "SerpentSting",
            "flags": ["APL"],
        },
        {
            "action_id": None,
            "rank": 0,
            "class_spell": "PassiveProc",
            "flags": [],
        },
    ]
    cooldowns = [{"action_id": {"spell_id": 3045}}]
    candidate_calls = []

    def prepare(**kwargs):
        scenario = kwargs["scenario"]
        if scenario.endswith("native-candidate-13550"):
            candidate_calls.append(kwargs)
            return {
                "status": "UNSUPPORTED",
                "stage": "prepare",
                "reason": "NATIVE_PREPARED_GATE_REFUSED",
                "refusal": {"code": "UNSUPPORTED_NATIVE_ACTION"},
                "engine_identity": "selected-pin",
                "request_sha256": "c" * 64,
            }
        marker = "with" if scenario.endswith("with-action") else "without"
        digest = ("a" if marker == "with" else "b") * 64
        return {
            "status": "PREPARED",
            "stage": "prepare",
            "engine_identity": "selected-pin",
            "request_sha256": digest,
            "prepared_sha256": digest,
            "prepared": {
                "marker": marker,
                "player": {
                    "class": "Hunter",
                    "level": 20,
                    "talents_string": "123",
                    "talents": {},
                    "spells": spellbook,
                    "major_cooldowns": cooldowns,
                },
            },
        }

    def simulate(**kwargs):
        marker = kwargs["prepared"]["marker"]
        return {
            "status": "EXECUTED",
            "stage": "sim",
            "dps": 18.0 if marker == "with" else 4.0,
            "engine_identity": "selected-pin",
        }

    monkeypatch.setattr(probe, "prepare_native_request", prepare)
    monkeypatch.setattr(probe, "_simulate_prepared", simulate)
    monkeypatch.setattr(
        probe, "_run_world_bridge",
        lambda *args, **kwargs: pytest.fail("non-spatial probe must not start 2D"),
    )

    result = probe.run_native_p1_direct_effect_probe(
        binary=binary,
        engine_root=engine_root,
        request=_sample_request(),
        spell_id=14282,
        timeout_seconds=5,
        iterations=1,
        requires_2d_world=False,
        target_count=0,
        world_mob_health=0,
    )

    inventory = result["native_prepared_action_inventory"]
    assert result["status"] == "NATIVE_DIRECT_EFFECT_VERIFIED"
    assert inventory["status"] == "AVAILABLE"
    assert inventory["spells"] == spellbook
    assert inventory["spell_count"] == 3
    assert inventory["major_cooldown_count"] == 1
    assert inventory["p1_certified"] is False
    assert result["native_action_inventory_parity"]["status"] == "MATCH"
    assert result["native_action_inventory_parity"]["positive_spell_records_equal"] is True
    assert result["native_action_inventory_parity"]["positive_major_cooldowns_equal"] is True
    candidate_probe = result["native_action_candidate_probe"]
    assert candidate_probe["status"] == "AVAILABLE"
    assert candidate_probe["candidate_scope"] == "NATIVE_PREPARED_APL_SPELLS_ONLY"
    assert candidate_probe["candidate_count"] == 2
    assert candidate_probe["prepared_count"] == 1
    assert candidate_probe["unsupported_count"] == 1
    assert candidate_probe["non_apl_spell_record_count"] == 1
    assert candidate_probe["major_cooldowns_probed"] is False
    assert candidate_probe["candidate_results"][0]["native_status"] == "PREPARED"
    assert candidate_probe["candidate_results"][0]["reused_selected_prepare"] is True
    assert candidate_probe["candidate_results"][1]["native_status"] == "UNSUPPORTED"
    assert candidate_probe["candidate_results"][1]["prepare_receipt"]["refusal"] == {
        "code": "UNSUPPORTED_NATIVE_ACTION"
    }
    assert len(candidate_calls) == 1
    candidate_player = candidate_calls[0]["request"]["raid"]["parties"][0]["players"][0]
    assert candidate_player["rotation"]["priorityList"] == [
        {"action": {"castSpell": {"spellId": {"spellId": 13550}}}}
    ]
    assert result["p1_certified"] is False



def test_native_action_inventory_parity_fails_closed_on_mismatch():
    from src.engine_client.native_p1_effect_probe import _native_action_inventory_parity

    positive = {
        "status": "AVAILABLE",
        "spells": [{"action_id": {"spell_id": 14282}}],
        "major_cooldowns": [],
        "spell_count": 1,
        "major_cooldown_count": 0,
    }
    control = {
        "status": "AVAILABLE",
        "spells": [],
        "major_cooldowns": [],
        "spell_count": 0,
        "major_cooldown_count": 0,
    }

    result = _native_action_inventory_parity(positive, control)

    assert result["status"] == "MISMATCH"
    assert result["positive_spell_records_equal"] is False
    assert result["positive_major_cooldowns_equal"] is True
