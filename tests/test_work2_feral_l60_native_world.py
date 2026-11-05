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
