"""Forever-owned Feral L60 native/world request and receipt transport tests."""
import copy
import hashlib
import json

import pytest

from tools.wf_native_feral_l60_world import run_feral_l60_world


def _source():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassDruid",  # Original Feral source has no level field.\n            "talents": {"string": "source-owned"},
            "rotation": {"priorityList": [{"action": {"castSpell": {
                "spellId": {"spellId": 1}}}}]},
            "equipment": {"items": [{"id": 42}]},
        }]}]},
        "encounter": {"targets": [{
            "level": 63, "stats": [0] * 32 + [127393],
            "minBaseDamage": 3000, "swingSpeed": 2,
        }]},
        "simOptions": {"iterations": 1},
    }


def _world_receipt(count):
    return {
        "continuous_native_actor": True, "actual_2d_ack": True,
        "world_targets_killed": count, "paid_recovery": True,
        "world_kills": [{"target_id": f"m{i}"} for i in range(count)],
        "native_windows": [{"index": i} for i in range(count)],
        "world_elapsed_seconds": 12.5,
    }


def test_feral_l60_uses_native_prepared_source_and_same_world_actor(tmp_path):
    source = _source()
    source_path = tmp_path / "source.json"
    raw = json.dumps(source).encode()
    source_path.write_bytes(raw)
    observed = []

    def prepare(argv, **kwargs):
        assert argv[1:3] == ["prepare", "--request"]
        assert "--go-rules" in argv
        request = json.loads(open(argv[3], encoding="utf-8").read())
        observed.append(request)
        prepared_path = argv[argv.index("--outfile") + 1]
        with open(prepared_path, "w", encoding="utf-8") as f:
            json.dump({"player": {"class": "ClassDruid", "level": 60},
                       "request_sha256": "a" * 64}, f)

    def world(binary, prepared, **kwargs):
        observed.append(("world", kwargs))
        assert json.loads(prepared.read_text())["request_sha256"] == "a" * 64
        return _world_receipt(2)

    result = run_feral_l60_world(
        tmp_path / "selected-native", source_path,
        world_run=world, prepare_run=prepare)
    native_request = observed[0]
    assert native_request["raid"] == source["raid"]
    assert native_request["encounter"]["targets"][0]["level"] == 60
    assert native_request["encounter"]["targets"][0]["stats"][32] == 3052
    assert native_request["encounter"]["targets"][0]["minBaseDamage"] == 100.
    assert observed[1] == ("world", {
        "classic_mob_level": 60, "target_count": 2,
        "rng_mode": "balanced", "require_native_moving": True,
    })
    assert json.loads(source_path.read_text()) == source
    assert result["source_request_raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["native_world"]["world_targets_killed"] == 2
    assert result["objective_100_mobs"] is None
    assert result["p4_p5_p6_certified"] is False


def test_feral_l60_rejects_non_source_actor_before_native(tmp_path):
    source = _source()
    source["raid"]["parties"][0]["players"][0]["class"] = "ClassPriest"
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="FERAL_L60_SOURCE_ACTOR_OR_TARGET_INVALID"):
        run_feral_l60_world("/native", path, world_run=lambda *a, **k: None)


def test_feral_l60_rejects_incomplete_world_without_gate_credit(tmp_path):
    path = tmp_path / "feral.json"
    path.write_text(json.dumps(_source()))

    def prepare(argv, **kwargs):
        with open(argv[argv.index("--outfile") + 1], "w") as f:
            json.dump({"player": {"class": "ClassDruid", "level": 60},
                       "request_sha256": "b" * 64}, f)

    incomplete = _world_receipt(2)
    incomplete["world_kills"][1]["target_id"] = "m0"
    with pytest.raises(RuntimeError, match="FERAL_L60_NATIVE_WORLD_RECEIPT_INCOMPLETE"):
        run_feral_l60_world("/native", path, prepare_run=prepare,
                            world_run=lambda *a, **k: incomplete)


def test_feral_l60_rejects_invalid_target_count_without_work(tmp_path):
    with pytest.raises(ValueError, match="FERAL_L60_WORLD_TARGET_COUNT_INVALID"):
        run_feral_l60_world("/native", tmp_path / "not-read.json",
                            target_count=1)

def test_feral_l60_propagates_native_prepare_refusal(tmp_path):
    import subprocess

    path = tmp_path / "feral.json"
    path.write_text(json.dumps(_source()))

    def refused(argv, **kwargs):
        raise subprocess.CalledProcessError(
            5, argv, stderr="MythicSim UNSUPPORTED: source build refusal")

    with pytest.raises(RuntimeError, match=(
            "FERAL_L60_NATIVE_PREPARE_REFUSED:exit=5:"
            "MythicSim UNSUPPORTED: source build refusal")):
        run_feral_l60_world("/native", path, prepare_run=refused,
                            world_run=lambda *a, **k: None)


def _prepared_feral(argv, **kwargs):
    with open(argv[argv.index("--outfile") + 1], "w", encoding="utf-8") as out:
        json.dump({"player": {"class": "ClassDruid", "level": 60},
                   "request_sha256": "c" * 64}, out)


def _paid_100_receipt():
    receipt = _world_receipt(100)
    receipt.update({
        "world_elapsed_seconds": 1100.0,
        "gsim_route_paid_movement_s": 297.0,
        "gsim_route_paid_receipts": [
            {"target_id": f"m{i}"} for i in range(1, 100)],
        "native_passive_recovery_observed": True,
        "native_passive_recovery_ns_by_target": [0] + [2_000_000_000] * 99,
        "minimum_native_actor_health": 123.0,
    })
    return receipt


def test_feral_l60_100_mob_objective_uses_paid_native_world_receipts(tmp_path):
    path = tmp_path / "feral.json"
    path.write_text(json.dumps(_source()), encoding="utf-8")

    def world(binary, prepared, **kwargs):
        assert kwargs["target_count"] == 100
        assert kwargs["rng_mode"] == "balanced"
        assert kwargs["require_native_moving"] is True
        return _paid_100_receipt()

    result = run_feral_l60_world(
        "/native", path, target_count=100,
        prepare_run=_prepared_feral, world_run=world)
    objective = result["objective_100_mobs"]
    assert objective == {
        "targets": 100,
        "mean_seconds_per_mob": 11.0,
        "total_elapsed_seconds": 1100.0,
        "paid_world_movement_seconds": 297.0,
        "native_passive_recovery_seconds": 198.0,
        "minimum_native_actor_health": 123.0,
    }
    assert result["p4_p5_p6_certified"] is False


def test_feral_l60_100_mob_rejects_unpaid_recovery(tmp_path):
    path = tmp_path / "feral.json"
    path.write_text(json.dumps(_source()), encoding="utf-8")
    receipt = _paid_100_receipt()
    receipt["paid_recovery"] = False
    with pytest.raises(RuntimeError, match="FERAL_L60_100_MOB_PAID_OBJECTIVE_INCOMPLETE"):
        run_feral_l60_world(
            "/native", path, target_count=100,
            prepare_run=_prepared_feral,
            world_run=lambda *args, **kwargs: receipt)


@pytest.mark.parametrize("missing", [
    "native_passive_recovery_observed",
    "native_passive_recovery_ns_by_target",
    "gsim_route_paid_receipts", "gsim_route_paid_movement_s",
    "minimum_native_actor_health", "world_elapsed_seconds",
])
def test_feral_l60_100_mob_objective_refuses_incomplete_paid_receipts(
        tmp_path, missing):
    path = tmp_path / "feral.json"
    path.write_text(json.dumps(_source()), encoding="utf-8")
    receipt = _paid_100_receipt()
    receipt.pop(missing)
    with pytest.raises(RuntimeError, match="FERAL_L60_100_MOB_PAID_OBJECTIVE_INCOMPLETE"):
        run_feral_l60_world(
            "/native", path, target_count=100,
            prepare_run=_prepared_feral,
            world_run=lambda *args, **kwargs: receipt)


def test_feral_l60_forwards_paid_native_recovery_candidate(tmp_path):
    path = tmp_path / "feral.json"
    path.write_text(json.dumps(_source()), encoding="utf-8")
    seen = {}

    def world(binary, prepared, **kwargs):
        seen.update(kwargs)
        return _paid_100_receipt()

    result = run_feral_l60_world(
        "/native", path, target_count=100, recovery_seconds=24,
        prepare_run=_prepared_feral, world_run=world)
    assert seen["native_recovery_seconds"] == 24
    assert seen["rng_mode"] == "balanced"
    assert result["requested_native_recovery_seconds"] == 24
    assert result["objective_100_mobs"]["targets"] == 100


@pytest.mark.parametrize("bad", [0, 121, -1, True, 2.5, "24"])
def test_feral_l60_rejects_invalid_rest_choice_before_native(tmp_path, bad):
    with pytest.raises(ValueError, match="FERAL_L60_WORLD_RECOVERY_SECONDS_INVALID"):
        run_feral_l60_world(
            "/native", tmp_path / "absent.json",
            recovery_seconds=bad,
            world_run=lambda *args, **kwargs: None)


def test_native_paid_rest_candidate_requires_exact_engine_ack():
    import sys
    from pathlib import Path
    integration = Path(__file__).resolve().parents[1] / "integrations" / "mythicsim-rust"
    sys.path.insert(0, str(integration))
    from live_two_world_pulls import _native_recovery_choice_ack

    assert _native_recovery_choice_ack(
        {"recovery_seconds_per_gap": 24}, 24) == 24
    assert _native_recovery_choice_ack({}, None) is None  # old native default
    assert _native_recovery_choice_ack(
        {"recovery_seconds_per_gap": 12}, None) == 12
    for actual in (None, 12, "24", True):
        with pytest.raises(AssertionError, match=(
                "RUST_WORLD_NATIVE_RECOVERY_CHOICE_NOT_ACKED:requested=24")):
            _native_recovery_choice_ack(
                {"recovery_seconds_per_gap": actual}, 24)


def test_native_paid_recovery_argv_and_first_dead_receipt():
    import sys
    from pathlib import Path
    integration = Path(__file__).resolve().parents[1] / "integrations" / "mythicsim-rust"
    sys.path.insert(0, str(integration))
    from live_two_world_pulls import _native_world_pulls_argv, _native_survival_min_health

    binary, prepared = Path("/bin/forever-engine"), Path("/tmp/prepared.json")
    default = _native_world_pulls_argv(binary, prepared, 100, "balanced", None)
    assert default[-2:] == ["--rng-mode", "balanced"]
    candidate = _native_world_pulls_argv(binary, prepared, 100, "balanced", 36)
    assert candidate == default + ["--recovery-seconds", "36"]
    with pytest.raises(ValueError, match="RUST_WORLD_RECOVERY_SECONDS_INVALID"):
        _native_world_pulls_argv(binary, prepared, 100, "balanced", 0)

    windows = [
        {"index": 0, "actor_health": 150., "actor_mana": 100.,
         "native_health_damage_taken": 20., "native_passive_recovery_ns": 0,
         "native_passive_recovery_ticks": 0},
        {"index": 1, "actor_health": 40., "actor_mana": 70.,
         "native_health_damage_taken": 110., "native_passive_recovery_ns": 12000000000,
         "native_passive_recovery_ticks": 6},
        {"index": 2, "actor_health": 0., "actor_mana": 50.,
         "native_health_damage_taken": 80., "native_passive_recovery_ns": 12000000000,
         "native_passive_recovery_ticks": 6},
    ]
    with pytest.raises(AssertionError) as failure:
        _native_survival_min_health(windows, 3)
    message = str(failure.value)
    assert "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=2" in message
    assert '"actor_health": 40.0' in message
    assert '"actor_health": 0.0' in message
    assert '"native_health_damage_taken": 80.0' in message


def test_paid_survival_search_rejects_real_native_death_and_scores_only_survivors(tmp_path):
    from tools.wf_native_feral_l60_world import search_feral_native_recovery

    path = tmp_path / "feral.json"
    path.write_text(json.dumps(_source()), encoding="utf-8")
    seen = []

    def world(binary, prepared, **kwargs):
        seconds = kwargs["native_recovery_seconds"]
        seen.append(seconds)
        assert kwargs["target_count"] == 100
        assert kwargs["rng_mode"] == "balanced"
        if seconds == 24:
            raise AssertionError(
                "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=62:"
                'adjacent_native_windows=[{"actor_health":284.0},{"actor_health":0.0}]')
        receipt = _paid_100_receipt()
        receipt["world_elapsed_seconds"] = 1500.0 if seconds == 48 else 1350.0
        receipt["minimum_native_actor_health"] = 40.0 if seconds == 48 else 80.0
        return receipt

    scored = search_feral_native_recovery(
        "/native", path, recovery_candidates=(24, 48, 72),
        world_run=world, prepare_run=_prepared_feral)
    assert seen == [24, 48, 72]
    assert scored["p4_p5_p6_certified"] is False
    assert scored["paid_native_attempts"][0]["native_survived"] is False
    assert scored["paid_native_attempts"][0]["first_native_death_index"] == 62
    assert '"actor_health":0.0' in scored["paid_native_attempts"][0]["native_failure"]
    assert scored["best_surviving_candidate"] == {
        "recovery_seconds": 72, "native_survived": True,
        "mean_seconds_per_mob": 13.5,
        "minimum_native_actor_health": 80.0,
    }


def test_paid_survival_search_propagates_transport_failure_and_refuses_all_dead(tmp_path):
    from tools.wf_native_feral_l60_world import search_feral_native_recovery

    path = tmp_path / "feral.json"
    path.write_text(json.dumps(_source()), encoding="utf-8")

    def dead(binary, prepared, **kwargs):
        raise AssertionError(
            "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=62:"
            "adjacent_native_windows=[]")

    with pytest.raises(RuntimeError, match=(
            "FERAL_L60_NO_SURVIVING_NATIVE_RECOVERY_CANDIDATE:")) as failure:
        search_feral_native_recovery(
            "/native", path, recovery_candidates=(48,),
            world_run=dead, prepare_run=_prepared_feral)
    assert '"first_native_death_index": 62' in str(failure.value)

    def broken(binary, prepared, **kwargs):
        raise AssertionError("RUST_TWO_WORLD_KILL_CLOCK_NOT_CAUSAL")
    with pytest.raises(AssertionError, match="RUST_TWO_WORLD_KILL_CLOCK_NOT_CAUSAL"):
        search_feral_native_recovery(
            "/native", path, recovery_candidates=(48,),
            world_run=broken, prepare_run=_prepared_feral)


@pytest.mark.parametrize("candidates", [
    (), (0,), (121,), (24, 24), (True,), ("24",), (24, 48, 72, 96, 120),
])
def test_paid_survival_search_invalid_budget_before_prepare(tmp_path, candidates):
    from tools.wf_native_feral_l60_world import search_feral_native_recovery

    with pytest.raises(ValueError, match="FERAL_L60_RECOVERY_CANDIDATES_INVALID"):
        search_feral_native_recovery(
            "/native", tmp_path / "missing.json",
            recovery_candidates=candidates)
