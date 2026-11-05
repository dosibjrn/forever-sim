"""Native Feral chest-source candidate selection: real paid score, no shadow rules."""
import json
import subprocess

import pytest

from tools.wf_native_feral_survival_gear import search_feral_native_chest_survival


def source():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassDruid",
            "equipment": {"items": [{"id": 100 + i} for i in range(16)]},
        }]}]},
        "encounter": {"targets": [{
            "level": 63, "stats": [0] * 32 + [127393],
            "minBaseDamage": 3000, "swingSpeed": 2,
        }]},
        "simOptions": {"iterations": 1},
    }


def options(binary, class_key, level, **kwargs):
    assert class_key == "druid" and level == 60
    assert kwargs == {"spec": "unrestricted", "slot": "chest"}
    return {"items": [
        {"item_id": 104, "stats": {"Stamina": 99.0}},
        {"item_id": 205, "stats": {"Stamina": 41.0}},
        {"item_id": 206, "stats": {"Stamina": 54.0}},
        {"item_id": 207, "stats": {"Stamina": 20.0}},
    ]}


def prepare(argv, **kwargs):
    candidate = json.loads(open(argv[3], encoding="utf-8").read())
    item = candidate["raid"]["parties"][0]["players"][0]["equipment"]["items"][4]
    assert set(item) == {"id"}  # no stale source enchant or synthetic stats
    with open(argv[argv.index("--outfile") + 1], "w", encoding="utf-8") as f:
        json.dump({"player": {"class": "ClassDruid", "level": 60},
                   "request_sha256": "a" * 64,
                   "selected_item": item["id"]}, f)


def paid_world(binary, prepared, **kwargs):
    assert kwargs["target_count"] == 100
    assert kwargs["rng_mode"] == "balanced"
    assert kwargs["native_recovery_seconds"] == 24
    item = json.loads(prepared.read_text())["selected_item"]
    if item == 206:
        raise AssertionError(
            "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=39:"
            'adjacent_native_windows=[{"actor_health":0}]')
    elapsed = 1500. if item == 205 else 1250.
    return {
        "continuous_native_actor": True, "actual_2d_ack": True,
        "world_targets_killed": 100, "paid_recovery": True,
        "world_kills": [{"target_id": str(i)} for i in range(100)],
        "native_windows": [{"index": i} for i in range(100)],
        "world_elapsed_seconds": elapsed,
        "gsim_route_paid_movement_s": 297.,
        "gsim_route_paid_receipts": [{} for _ in range(99)],
        "native_passive_recovery_observed": True,
        "native_passive_recovery_ns_by_target": [0] + [24_000_000_000] * 99,
        "minimum_native_actor_health": 70.,
    }


def test_native_options_produce_distinct_prepared_persistent_candidates(tmp_path):
    path = tmp_path / "feral.json"
    path.write_text(json.dumps(source()))
    result = search_feral_native_chest_survival(
        "/native", path, native_options=options, max_candidates=3,
        prepare_run=prepare, world_run=paid_world)
    attempts = result["native_paid_gear_attempts"]
    assert [a["chest_item_id"] for a in attempts] == [206, 205, 207]
    assert attempts[0]["status"] == "native_death"
    assert attempts[0]["first_native_death_index"] == 39
    assert attempts[1]["status"] == "survived"
    assert result["best_surviving_candidate"]["chest_item_id"] == 207
    assert result["best_surviving_candidate"]["mean_seconds_per_mob"] == 12.5
    assert result["p4_p5_p6_certified"] is False
    assert json.loads(path.read_text()) == source()


def test_native_preparation_refusal_is_not_scored(tmp_path):
    path = tmp_path / "feral.json"
    path.write_text(json.dumps(source()))

    def refuse(argv, **kwargs):
        raise subprocess.CalledProcessError(
            4, argv, stderr="INVALID: native combined build")

    with pytest.raises(RuntimeError, match="NO_SURVIVING_NATIVE_CHEST_CANDIDATE") as exc:
        search_feral_native_chest_survival(
            "/native", path, native_options=options, max_candidates=1,
            prepare_run=refuse, world_run=paid_world)
    assert '"status": "native_refused"' in str(exc.value)
    assert "INVALID: native combined build" in str(exc.value)


@pytest.mark.parametrize("budget", [0, 5, True, 1.0])
def test_candidate_budget_rejected_before_native(tmp_path, budget):
    with pytest.raises(ValueError, match="NATIVE_GEAR_CANDIDATE_BUDGET_INVALID"):
        search_feral_native_chest_survival(
            "/native", tmp_path / "absent.json", max_candidates=budget)
