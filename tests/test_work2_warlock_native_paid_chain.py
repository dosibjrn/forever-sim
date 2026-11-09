"""Forever-owned L20 8/100-mob paid-recovery transport/receipt contracts.

Mocks only the Rust subprocess boundary. No Python food, regen, combat or
legality oracle; real native/world behavior is checked by separate Actions.
"""
from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
_WORLD = runpy.run_path(str(ROOT / "integrations/mythicsim-rust/live_two_world_pulls.py"))
_WARLOCK = runpy.run_path(str(ROOT / "tools/wf_warlock_l20_100mob.py"))
_cli = _WORLD["_native_recovery_cli_args"]
_food = _WORLD["_native_food_water_receipts"]


def test_recovery_cli_preserves_default_and_forwards_both_native_policies():
    assert _cli(None, None, 0.5, 0.1) == (None, [])
    assert _cli("fixed", 17, 0.5, 0.1) == (
        "fixed", ["--recovery-seconds", "17"])
    assert _cli("decisions", None, 0.45, 0.2) == (
        "decisions", ["--recovery-policy", "decisions",
                      "--health-threshold", "0.45",
                      "--mana-threshold", "0.2"])


@pytest.mark.parametrize("policy,seconds,hp,mana", [
    ("fixed", 0, 0.5, 0.1),
    ("fixed", 121, 0.5, 0.1),
    ("fixed", True, 0.5, 0.1),
    ("decisions", 12, 0.5, 0.1),
    ("decisions", None, float("nan"), 0.1),
    ("decisions", None, 0.5, -0.1),
    ("unknown", None, 0.5, 0.1),
])
def test_bad_recovery_request_fails_before_native_launch(policy, seconds, hp, mana):
    with pytest.raises(ValueError):
        _cli(policy, seconds, hp, mana)


def _food_window(ns, *, food=0., water=0., health=0., mana=0., full=False):
    return {"native_passive_recovery_ns": ns, "food_seconds": food,
            "water_seconds": water, "food_health_gain": health,
            "water_mana_gain": mana, "decisions_full_recovery": full}


def test_food_water_is_native_reported_clock_paid_not_assumed():
    receipt = _food([
        _food_window(0),
        _food_window(5_000_000_000, food=3., water=4.,
                     health=70., mana=120., full=True)], required=True)
    assert receipt["native_food_water_observed"] is True
    assert receipt["native_food_seconds_total"] == 3.
    assert receipt["native_water_seconds_total"] == 4.
    assert receipt["native_food_health_gain_total"] == 70.
    assert receipt["native_water_mana_gain_total"] == 120.
    assert len(receipt["native_food_water_by_target"]) == 2
    assert _food([{"native_passive_recovery_ns": 0}], required=False) == {
        "native_food_water_observed": False}


def test_missing_or_unpaid_native_consumption_cannot_become_paid_food_receipt():
    with pytest.raises(AssertionError, match="INCOMPLETE"):
        _food([_food_window(0), {"native_passive_recovery_ns": 5_000_000_000}],
              required=True)
    with pytest.raises(AssertionError, match="CLOCK_INVALID"):
        _food([_food_window(0), _food_window(2_000_000_000, water=5., mana=50.)],
              required=True)
    with pytest.raises(AssertionError, match="CLOCK_INVALID"):
        _food([_food_window(0), _food_window(2_000_000_000, water=0., mana=50.)],
              required=True)


def _source_request():
    return {
        "encounter": {"targets": [{"level": 20, "name": "source",
                                   "stats": [0.] * 33}]},
        "simOptions": {"iterations": 1, "randomSeed": "42"},
        "raid": {"parties": [{"players": [{
            "class": "ClassWarlock", "race": "RaceTroll",
            "equipment": {"items": [{"id": i} for i in range(1, 18)]},
            "rotation": {"priorityList": []},
        }]}]},
    }


@pytest.mark.parametrize("targets,paid", [
    (8, True), (100, True), (8, False), (100, False),
])
def test_warlock_driver_forwards_native_decisions_and_never_scores_unpaid_or_8_as_100(
    tmp_path, monkeypatch, targets, paid
):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_source_request()), encoding="utf-8")
    out = tmp_path / "out"
    observed = []

    def prepare(cmd, **kwargs):
        assert cmd[1] == "prepare" and "--actor-level" in cmd
        prepared = Path(cmd[cmd.index("--outfile") + 1])
        prepared.write_text(json.dumps({"player": {
            "class": "ClassWarlock", "race": "RaceTroll", "level": 20,
            "stats": {"Health": 600., "Mana": 700.}}}), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def native(_binary, _prepared, **kwargs):
        observed.append(kwargs)
        assert kwargs["target_count"] == targets
        return {
            "world_targets_killed": targets,
            "world_elapsed_seconds": targets * 7.,
            "world_seconds_per_target_paid_recovery": 7. if paid else None,
            "minimum_native_actor_health": 150.,
            "minimum_native_actor_mana": 20.,
            "native_windows": [{"actor_health": 150.}] * targets,
            "native_actor_mana_after_world_kills": [300.] * targets,
            "paid_recovery": paid,
            "native_recovery_mode": "decisions_food_water",
            "native_passive_recovery_elapsed_seconds": 6. * (targets - 1),
            "native_passive_recovery_ns_by_target": [0] + [6_000_000_000] * (targets - 1),
            "native_passive_recovery_ticks_by_target": [0] + [3] * (targets - 1),
            "native_food_water_observed": True,
            "native_food_seconds_total": 3.,
            "native_water_seconds_total": 4.,
            "native_food_health_gain_total": 70.,
            "native_water_mana_gain_total": 120.,
            "gsim_route_paid_movement_s": 2.,
            "native_damage_events": targets,
        }

    main = _WARLOCK["main"]
    monkeypatch.setitem(main.__globals__, "native_world_chain", native)
    monkeypatch.setattr(main.__globals__["subprocess"], "run", prepare)
    monkeypatch.setattr(sys, "argv", [
        "wf_warlock_l20_100mob.py", "--binary", str(tmp_path / "engine"),
        "--source", str(source), "--out", str(out),
        "--variant", "best_apl", "--targets", str(targets),
        "--recovery-policy", "decisions",
        "--health-threshold", "0.45", "--mana-threshold", "0.20",
    ])
    if paid:
        main()
    else:
        with pytest.raises(SystemExit, match="with paid recovery"):
            main()

    assert len(observed) == 1
    assert observed[0]["recovery_policy"] == "decisions"
    assert observed[0]["health_threshold"] == 0.45
    assert observed[0]["mana_threshold"] == 0.2
    assert observed[0]["rng_mode"] == "balanced"
    record = json.loads((out / "best_apl" / "summary.json").read_text())
    assert record["killed"] == targets
    assert record["paid_recovery"] is paid
    assert record["seconds_per_mob"] == (7. if paid else None)
    assert record["status"] == (
        f"COMPLETED_{targets}_REAL_NATIVE_GSIM_KILLS"
        if paid else "INCOMPLETE_UNPAID_NATIVE_RECOVERY")
    assert record["native_2d_paid_objective_eligible"] is (
        paid and targets == 100)
    summary = json.loads((out / "summary.json").read_text())
    assert summary["p4_p5_p6_pass"] is False
    assert summary["cold_30_300_search_executed"] is False


def test_fixed_recovery_duration_forwarded_from_warlock_driver(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_source_request()), encoding="utf-8")
    observed = []

    def prepare(cmd, **kwargs):
        Path(cmd[cmd.index("--outfile") + 1]).write_text(json.dumps({
            "player": {"class": "ClassWarlock", "race": "RaceTroll",
                       "level": 20, "stats": {"Health": 600., "Mana": 700.}}}))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    def refuse(binary, prepared, **kwargs):
        observed.append(kwargs)
        raise AssertionError("RUST_TWO_WORLD_NATIVE_FAILED:3 kills")

    main = _WARLOCK["main"]
    monkeypatch.setitem(main.__globals__, "native_world_chain", refuse)
    monkeypatch.setattr(main.__globals__["subprocess"], "run", prepare)
    monkeypatch.setattr(sys, "argv", [
        "driver", "--binary", str(tmp_path / "engine"), "--source", str(source),
        "--out", str(tmp_path / "out"), "--targets", "8",
        "--variant", "best_apl", "--recovery-policy", "fixed",
        "--recovery-seconds", "17",
    ])
    with pytest.raises(SystemExit, match="No variant completed"):
        main()
    assert observed[0]["recovery_policy"] == "fixed"
    assert observed[0]["recovery_seconds"] == 17
    record = json.loads((tmp_path / "out/best_apl/summary.json").read_text())
    assert record["status"] == "INCOMPLETE_OR_NATIVE_REFUSAL"
    assert "3 kills" in record["error"]



def test_native_refusal_preserves_only_source_acknowledged_partial_kills():
    capture = _WARLOCK["native_failure_receipt"]
    actual = AssertionError(("RUST_TWO_WORLD_NATIVE_FAILED", 19,
                             "native ran dry", 50, 623))
    assert capture(actual) == {
        "native_exit_code": 19,
        "native_world_ack_kills_before_refusal": 50,
        "native_damage_events_before_refusal": 623,
    }
    assert capture(AssertionError("50 kills maybe")) == {}
    assert capture(AssertionError(("RUST_TWO_WORLD_NATIVE_FAILED", 0,
                                   "no failure", 100, 1000))) == {}
    assert capture(ValueError("bad request")) == {}


def test_native_failure_records_real_partial_ack_count_not_completion(
    tmp_path, monkeypatch
):
    """A dry native actor may kill some mobs; report the exact ACK count."""
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_source_request()), encoding="utf-8")
    out = tmp_path / "out"

    def prepare(cmd, **kwargs):
        Path(cmd[cmd.index("--outfile") + 1]).write_text(json.dumps({
            "player": {"class": "ClassWarlock", "race": "RaceTroll",
                       "level": 20, "stats": {"Health": 600., "Mana": 700.}}}))
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    refusal = _WARLOCK["NativeWorldChainFailure"](
        "RUST_TWO_WORLD_NATIVE_FAILED", 17, "native actor exhausted", 51, 87)
    def native(*args, **kwargs):
        raise refusal

    main = _WARLOCK["main"]
    monkeypatch.setitem(main.__globals__, "native_world_chain", native)
    monkeypatch.setattr(main.__globals__["subprocess"], "run", prepare)
    monkeypatch.setattr(sys, "argv", [
        "driver", "--binary", str(tmp_path / "engine"), "--source", str(source),
        "--out", str(out), "--targets", "100", "--variant", "best_apl",
        "--recovery-policy", "fixed", "--recovery-seconds", "12",
    ])
    with pytest.raises(SystemExit, match="No variant completed 100"):
        main()

    record = json.loads((out / "best_apl/summary.json").read_text())
    assert record["status"] == "INCOMPLETE_OR_NATIVE_REFUSAL"
    assert record["killed"] == 51
    assert record["native_damage_events"] == 87
    assert record["native_exit_code"] == 17
    assert "seconds_per_mob" not in record
    assert record["native_2d_paid_objective_eligible"] is False
    assert "exhausted" in record["error"]
    summary = json.loads((out / "summary.json").read_text())
    assert summary["p4_p5_p6_pass"] is False
