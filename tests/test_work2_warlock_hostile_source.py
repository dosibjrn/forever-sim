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
