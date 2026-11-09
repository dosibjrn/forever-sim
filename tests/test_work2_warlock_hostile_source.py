"""Work2 hostile Warlock scenario transport; no Python enemy-combat oracle.

The native prepared enemy is authoritative for whether the request registered
attacks. Positive player hits are deliberately *not* an acceptance condition.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import wf_warlock_l20_100mob as chain
from tools import wf_warlock_l20_native_cold as cold


def _request():
    return {
        "simOptions": {"iterations": 8, "randomSeed": "42"},
        "encounter": {"targets": [{
            "level": 20, "name": "Stationary L20 native APL smoke",
            "stats": [0.0] * 33,
            "minBaseDamage": 33.0, "swingSpeed": 1.6,
        }]},
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "race": "RaceTroll",
            "equipment": {"items": [{"id": i} for i in range(1, 18)]},
            "rotation": {"priorityList": []},
        }]}]},
    }


def test_native_hostile_scenario_assigns_player_tank_without_mutating_source():
    source = _request()
    original = copy.deepcopy(source)
    hostile = chain.create_scenario(
        source, variant="best_apl", hostile_player_tank=True)
    target = hostile["encounter"]["targets"][0]
    assert hostile["raid"]["tanks"] == [{"type": "Player", "index": 0}]
    assert target["tankIndex"] == 0
    assert target["minBaseDamage"] == 33.0
    assert target["swingSpeed"] == 1.6
    assert target["name"] == "Hostile L20 player-tanked native world enemy"
    assert source == original

    stationary = chain.create_scenario(source, variant="best_apl")
    assert "tanks" not in stationary["raid"]
    assert "tankIndex" not in stationary["encounter"]["targets"][0]
    assert stationary["encounter"]["targets"][0]["name"] == (
        "Stationary L20 native APL smoke")


@pytest.mark.parametrize("items", [
    [],
    [{"id": 100}],
    [{"id": i} for i in range(1, 18)],
])
def test_native_cold_actor_equipment_reaches_prepare_without_python_slot_veto(items):
    """The genuine unseeded cold source must reach Rust unchanged, even empty.

    A former exactly-17-equipment assertion in create_scenario rejected both
    the first unseeded baseline and one-item gear insertions before prepare.
    Python must not pad gear or judge a build's source legality.
    """
    source = _request()
    source["raid"]["parties"][0]["players"][0]["equipment"]["items"] = copy.deepcopy(items)
    frozen = copy.deepcopy(source)
    scenario = chain.create_scenario(
        source, variant="best_apl", hostile_player_tank=True)
    forwarded = scenario["raid"]["parties"][0]["players"][0]["equipment"]["items"]
    assert forwarded == items
    assert scenario["raid"]["tanks"] == [{"type": "Player", "index": 0}]
    assert source == frozen


def test_hostile_request_without_native_prepared_enemy_is_a_real_refusal(
    tmp_path, monkeypatch
):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_request()), encoding="utf-8")
    binary = tmp_path / "engine"
    binary.write_bytes(b"mock native binary")
    out = tmp_path / "results"
    observed = []

    def prepare(command, **_kwargs):
        assert command[1] == "prepare"
        prepared_path = Path(command[command.index("--outfile") + 1])
        request_path = Path(command[command.index("--request") + 1])
        forwarded = json.loads(request_path.read_text())
        observed.append(forwarded)
        assert forwarded["raid"]["tanks"] == [{"type": "Player", "index": 0}]
        assert forwarded["encounter"]["targets"][0]["tankIndex"] == 0
        # Emulate a native prepare that does not register an enemy actor.
        prepared_path.write_text(json.dumps({"player": {
            "class": "ClassWarlock", "race": "RaceTroll", "level": 20,
            "stats": {"Health": 600.0, "Mana": 700.0},
        }}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(chain.subprocess, "run", prepare)
    monkeypatch.setattr(
        chain, "native_world_chain",
        lambda *_args, **_kwargs: pytest.fail(
            "native world must not run without requested prepared enemy"))
    monkeypatch.setattr(sys, "argv", [
        "wf_warlock_l20_100mob.py", "--binary", str(binary),
        "--source", str(source), "--out", str(out),
        "--variant", "best_apl", "--targets", "100",
        "--recovery-policy", "decisions", "--hostile-player-tank",
    ])
    with pytest.raises(SystemExit, match="No variant completed"):
        chain.main()
    assert len(observed) == 1
    row = json.loads((out / "best_apl/summary.json").read_text())
    assert row["status"] == "INCOMPLETE_OR_NATIVE_REFUSAL"
    assert row["hostile_player_tank_requested"] is True
    assert row["native_enemy_attack_prepared"] is False
    assert "NATIVE_HOSTILE_ENEMY_ATTACK_NOT_PREPARED" in row["error"]
    assert row["native_2d_paid_objective_eligible"] is False
    assert json.loads((out / "summary.json").read_text())[
        "p4_p5_p6_pass"] is False


@pytest.mark.parametrize("targets", [2, 100])
def test_cold_native_candidate_requests_real_hostile_source(
    tmp_path, monkeypatch, targets
):
    binary = tmp_path / "engine"
    binary.write_bytes(b"native engine")
    candidate = {"source": _request(), "recovery": {
        "health_threshold": 0.5, "mana_threshold": 0.1}}
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        assert "--hostile-player-tank" in command
        assert "--require-native-health-damage" not in command
        assert "--recovery-policy" in command
        assert command[command.index("--recovery-policy") + 1] == "decisions"
        assert command[command.index("--targets") + 1] == str(targets)
        # No summary: a paid native refusal must not be scored.
        return SimpleNamespace(returncode=1, stdout="", stderr="native refused")

    monkeypatch.setattr(cold.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="did not emit a structured receipt"):
        cold.paid_chain(binary, candidate, tmp_path / "attempt",
                        targets=targets, timeout=15)
    assert len(commands) == 1


@pytest.mark.parametrize("targets", [2, 100])
@pytest.mark.parametrize("hostile_requested,enemy_prepared,eligible", [
    (False, True, False),
    (True, False, False),
    (True, True, True),
])
def test_cold_scorer_requires_actual_hostile_native_receipt(
    tmp_path, monkeypatch, targets, hostile_requested, enemy_prepared, eligible
):
    """A completed-looking stationary receipt cannot become a cold winner.

    The native prepared enemy is authoritative. Zero actual player hits remain
    an eligible native result when both hostile transport flags are true.
    """
    import hashlib
    from native_matrix import NativeUnscoredCandidate

    binary = tmp_path / "engine"
    binary.write_bytes(b"pinned-native-engine")
    candidate = {
        "source": _request(),
        "recovery": {"health_threshold": 0.5, "mana_threshold": 0.1},
    }

    def paid_native(command, **_kwargs):
        assert "--hostile-player-tank" in command
        source = tmp_path / "attempt" / "candidate.request.json"
        summary = tmp_path / "attempt" / "world" / "summary.json"
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(json.dumps({"results": [{
            "original_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "native_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "recovery_request": {"recovery_policy": "decisions",
                                 **candidate["recovery"]},
            "target_count_requested": targets,
            "status": f"COMPLETED_{targets}_REAL_NATIVE_GSIM_KILLS",
            "hostile_player_tank_requested": hostile_requested,
            "native_enemy_attack_prepared": enemy_prepared,
            "native_actor_continuity_receipt_complete": True,
            "native_recovery_clock_accounted": True,
            "native_recovery_mode": "decisions_food_water",
            "native_2d_paid_objective_eligible": targets == 100,
            "seconds_per_mob": 13.2,
            "native_health_damage": {"damage_events": 0, "damage_taken": 0},
        }]}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cold.subprocess, "run", paid_native)
    if eligible:
        receipt = cold.paid_chain(
            binary, candidate, tmp_path / "attempt", targets=targets, timeout=20)
        assert receipt["seconds_per_mob"] == 13.2
    else:
        with pytest.raises(NativeUnscoredCandidate, match="incomplete/refused"):
            cold.paid_chain(
                binary, candidate, tmp_path / "attempt",
                targets=targets, timeout=20)

@pytest.mark.parametrize("reason, exit_code, detail", [
    ("RUST_TWO_WORLD_NATIVE_FAILED", 1, "actor died mid-chain"),
    ("RUST_TWO_WORLD_KILLS_NOT_COMPLETED", 0, "clean exit, incomplete kills"),
])
def test_partial_hostile_world_refusal_keeps_acked_native_actions_not_a_score(
    tmp_path, monkeypatch, reason, exit_code, detail
):
    """Both failed native paths preserve ACKed effects, never P4 credit."""
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_request()), encoding="utf-8")
    binary = tmp_path / "engine"
    binary.write_bytes(b"native executable fixture")
    out = tmp_path / "out"

    def prepare(command, **_kwargs):
        assert command[1] == "prepare"
        dest = Path(command[command.index("--outfile") + 1])
        dest.write_text(json.dumps({
            "player": {
                "class": "ClassWarlock", "race": "RaceTroll", "level": 20,
                "stats": {"Health": 600.0, "Mana": 700.0},
            },
            "enemy": {"prepared_by_rust": True},
            "request_sha256": "a" * 64,
        }))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def dead_native_actor(_binary, _prepared, **kwargs):
        assert kwargs["target_count"] == 100
        assert kwargs["recovery_policy"] == "decisions"
        counts = {"player": {"Spell-686": 60}, "pet": {"Pet-1": 20}}
        raise chain.NativeWorldChainFailure(
            reason, exit_code, detail, 47, 80, counts)

    monkeypatch.setattr(chain.subprocess, "run", prepare)
    monkeypatch.setattr(chain, "native_world_chain", dead_native_actor)
    monkeypatch.setattr(sys, "argv", [
        "wf_warlock_l20_100mob.py", "--binary", str(binary),
        "--source", str(source), "--out", str(out),
        "--variant", "best_apl", "--targets", "100",
        "--recovery-policy", "decisions", "--hostile-player-tank",
    ])
    with pytest.raises(SystemExit, match="No variant completed"):
        chain.main()

    attempt = json.loads((out / "best_apl/summary.json").read_text())
    assert attempt["status"] == "INCOMPLETE_OR_NATIVE_REFUSAL"
    assert attempt["native_chain_failure_reason"] == reason
    assert attempt["native_exit_code"] == exit_code
    assert attempt["native_world_ack_kills_before_refusal"] == 47
    assert attempt["native_damage_events_before_refusal"] == 80
    assert attempt["native_source_damage_effects_by_caster"] == {
        "player": {"Spell-686": 60}, "pet": {"Pet-1": 20}}
    assert attempt["native_2d_paid_objective_eligible"] is False
    assert "seconds_per_mob" not in attempt
    assert json.loads((out / "summary.json").read_text())[
        "p4_p5_p6_pass"] is False
