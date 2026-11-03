from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.engine_client import native_p1_action as p1
from src.engine_client.native_p2_rank_probe import NativeRngMode


ENGINE_SHA = "deb366e986dbc156e2242ddac3ac8c4ac854c107"


def _fixture_tree(tmp_path: Path) -> tuple[Path, Path]:
    engine_root = tmp_path / "engine"
    fixture = engine_root / "tests/classes/druid/prepare/cat.request.json"
    binary = engine_root / "target/release/forever-engine"
    fixture.parent.mkdir(parents=True)
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"selected-engine-test-double")
    fixture.write_text(
        json.dumps(
            {
                "raid": {
                    "parties": [
                        {
                            "players": [
                                {
                                    "class": "ClassDruid",
                                    "feralCatDruid": {},
                                    "talentsString": "test-build",
                                    "rotation": {
                                        "type": "TypeAPL",
                                        "priorityList": [
                                            {
                                                "action": {
                                                    "castSpell": {
                                                        "spellId": {"spellId": 9830}
                                                    }
                                                }
                                            }
                                        ],
                                    },
                                }
                            ]
                        }
                    ]
                },
                "simOptions": {
                    "iterations": 3000,
                    "randomSeed": "42",
                    "debugFirstIteration": True,
                },
            }
        ),
        encoding="utf-8",
    )
    return engine_root, binary


def test_native_prepared_v2_action_pair_measures_effect_and_only_changes_apl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine_root, binary = _fixture_tree(tmp_path)
    prepare_requests: list[dict[str, object]] = []
    sim_calls: list[dict[str, object]] = []
    scores = iter((145.0, 100.0))

    def fake_prepare(*, binary, request, scenario, deadline):
        prepare_requests.append(copy.deepcopy(request))
        index = len(prepare_requests)
        return {
            "status": "PREPARED",
            "scenario": scenario,
            "request_sha256": f"request-{index}",
            "prepared_sha256": f"prepared-{index}",
            "engine_identity": "selected-rust-engine",
            "prepared": {"sim": {"iterations": 100}},
            "elapsed_seconds": 0.01,
        }

    def fake_sim(*, binary_path, prepared, rng_mode, iterations, seed, deadline):
        sim_calls.append(
            {
                "prepared": prepared,
                "rng_mode": rng_mode,
                "iterations": iterations,
                "seed": seed,
            }
        )
        return {
            "status": "EXECUTED",
            "dps": next(scores),
            "engine_identity": "selected-rust-engine",
            "report_sha256": f"report-{len(sim_calls)}",
            "prepared_input_sha256": f"input-{len(sim_calls)}",
            "elapsed_seconds": 0.02,
        }

    monkeypatch.setattr(p1, "prepare_native_request", fake_prepare)
    monkeypatch.setattr(p1, "_simulate_prepared", fake_sim)

    result = p1.run_native_p1_action(
        binary=binary,
        engine_root=engine_root,
        spell_id=1082,
        action_id="claw:20",
        source_level_hint=20,
        engine_sha=ENGINE_SHA,
        iterations=100,
        seed=647003,
    )

    assert result["status"] == "NATIVE_EFFECT_OBSERVED"
    assert result["effect_observed"] is True
    assert result["p1_certified"] is False
    assert result["accepted_for_p1"] is False
    assert result["native_player_level_modeled"] is False
    assert result["native_authority"] == "MythicSim Rust PreparedV2"
    assert result["engine_commit_sha"] == ENGINE_SHA
    assert result["baseline_dps"] == 145.0
    assert result["control_dps"] == 100.0
    assert result["delta_dps"] == 45.0
    assert result["with_action_prepare"]["request_sha256"] != result["no_action_prepare"]["request_sha256"]
    assert len(prepare_requests) == 2
    assert len(sim_calls) == 2

    with_action = prepare_requests[0]
    no_action = prepare_requests[1]
    expected_control = copy.deepcopy(with_action)
    player = expected_control["raid"]["parties"][0]["players"][0]
    assert player["rotation"]["priorityList"] == [
        {"action": {"castSpell": {"spellId": {"spellId": 1082}}}}
    ]
    player["rotation"]["priorityList"] = []
    assert no_action == expected_control
    assert "level" not in with_action["raid"]["parties"][0]["players"][0]
    assert with_action["simOptions"]["iterations"] == no_action["simOptions"]["iterations"] == 100
    assert with_action["simOptions"]["randomSeed"] == no_action["simOptions"]["randomSeed"] == "647003"
    assert all(call["rng_mode"] is NativeRngMode.BALANCED for call in sim_calls)


@pytest.mark.parametrize("native_status", ["INVALID", "UNSUPPORTED", "ERROR", "BLOCKED"])
def test_native_prepare_refusal_is_authoritative_without_gameir_or_sim_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_status: str,
) -> None:
    engine_root, binary = _fixture_tree(tmp_path)
    sim_calls: list[object] = []

    def refused_prepare(*, binary, request, scenario, deadline):
        return {"status": native_status, "reason": "selected native refusal"}

    monkeypatch.setattr(p1, "prepare_native_request", refused_prepare)
    monkeypatch.setattr(p1, "_simulate_prepared", lambda **kwargs: sim_calls.append(kwargs))

    result = p1.run_native_p1_action(
        binary=binary,
        engine_root=engine_root,
        spell_id=1082,
        action_id="claw:20",
        source_level_hint=20,
        engine_sha=ENGINE_SHA,
    )

    assert result["status"] == native_status
    assert result["effect_observed"] is False
    assert result["p1_certified"] is False
    assert result["stage"] == "prepare_with_action"
    assert sim_calls == []


def test_native_sim_refusal_is_authoritative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine_root, binary = _fixture_tree(tmp_path)
    prepare_count = 0
    sim_count = 0

    def prepared(*, binary, request, scenario, deadline):
        nonlocal prepare_count
        prepare_count += 1
        return {
            "status": "PREPARED",
            "request_sha256": f"request-{prepare_count}",
            "prepared_sha256": f"prepared-{prepare_count}",
            "engine_identity": "selected-rust-engine",
            "prepared": {"sim": {}},
        }

    def refused_sim(**kwargs):
        nonlocal sim_count
        sim_count += 1
        return {"status": "UNSUPPORTED", "reason": "native sim refusal"}

    monkeypatch.setattr(p1, "prepare_native_request", prepared)
    monkeypatch.setattr(p1, "_simulate_prepared", refused_sim)

    result = p1.run_native_p1_action(
        binary=binary,
        engine_root=engine_root,
        spell_id=1082,
        action_id="claw:20",
        source_level_hint=20,
        engine_sha=ENGINE_SHA,
    )

    assert result["status"] == "UNSUPPORTED"
    assert result["effect_observed"] is False
    assert result["stage"] == "sim_with_action"
    assert prepare_count == 2
    assert sim_count == 1


def test_zero_or_non_effect_delta_does_not_count_as_observed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine_root, binary = _fixture_tree(tmp_path)
    prepare_count = 0
    sim_count = 0

    def prepared(*, binary, request, scenario, deadline):
        nonlocal prepare_count
        prepare_count += 1
        return {
            "status": "PREPARED",
            "request_sha256": f"request-{prepare_count}",
            "prepared_sha256": f"prepared-{prepare_count}",
            "engine_identity": "selected-rust-engine",
            "prepared": {"sim": {}},
        }

    def no_delta(**kwargs):
        nonlocal sim_count
        sim_count += 1
        return {
            "status": "EXECUTED",
            "dps": 100.0,
            "engine_identity": "selected-rust-engine",
        }

    monkeypatch.setattr(p1, "prepare_native_request", prepared)
    monkeypatch.setattr(p1, "_simulate_prepared", no_delta)

    result = p1.run_native_p1_action(
        binary=binary,
        engine_root=engine_root,
        spell_id=1082,
        action_id="claw:20",
        source_level_hint=20,
        engine_sha=ENGINE_SHA,
    )

    assert result["status"] == "NATIVE_EFFECT_NOT_OBSERVED"
    assert result["effect_observed"] is False
    assert result["p1_certified"] is False
    assert prepare_count == 2
    assert sim_count == 2
