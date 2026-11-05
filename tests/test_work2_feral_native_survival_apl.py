"""Work2 real-native APL ordering search: selection and refusal transport only."""
import json
import subprocess

import pytest

from tools.wf_native_feral_survival_apl import (
    _source_apl_candidates, search_feral_native_apl_survival,
)


def fixture():
    return {
        "raid": {"parties": [{"players": [{
            "class": "ClassDruid",
            "rotation": {"type": "TypeAPL", "priorityList": [
                {"action": {"castSpell": {"spellId": {"spellId": i}}}}
                for i in range(11, 17)
            ]},
        }]}]},
        "encounter": {"targets": [{
            "level": 60, "stats": [0] * 33, "minBaseDamage": 100.,
        }]},
    }


def write_source(tmp_path):
    path = tmp_path / "source.json"
    path.write_text(json.dumps(fixture()), encoding="utf-8")
    return path


def policy_label(request):
    ordered = [
        action["action"]["castSpell"]["spellId"]["spellId"]
        for action in request["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
    ]
    if ordered == [11, 12, 13, 14, 15, 16]:
        return "source"
    if ordered == [11, 12, 16, 13, 14, 15]:
        return "advance_last"
    if ordered == [11, 12, 15, 13, 14, 16]:
        return "advance_penultimate"
    raise AssertionError(f"UNEXPECTED_POLICY {ordered}")


def native_prepare(argv, **kwargs):
    assert argv[1] == "prepare" and "--go-rules" in argv
    request = json.loads(open(argv[argv.index("--request") + 1], encoding="utf-8").read())
    with open(argv[argv.index("--outfile") + 1], "w", encoding="utf-8") as handle:
        json.dump({
            "player": {"class": "ClassDruid", "level": 60},
            "request_sha256": "a" * 64,
            "policy": policy_label(request),
        }, handle)


def native_world(binary, prepared, **kwargs):
    assert kwargs["native_recovery_seconds"] == 24
    assert kwargs["rng_mode"] == "balanced"
    label = json.loads(prepared.read_text())["policy"]
    count = kwargs["target_count"]
    # All selected scores are source-native observations, not Python combat.
    health = {"source": 40., "advance_last": 85.,
              "advance_penultimate": 70.}[label]
    elapsed = {"source": 18., "advance_last": 15.,
               "advance_penultimate": 13.}[label]
    if count == 100 and label != "advance_last":
        raise AssertionError("Unexpected expensive replay")
    return {
        "continuous_native_actor": True,
        "actual_2d_ack": True,
        "world_targets_killed": count,
        "world_kills": [{"target_id": str(i)} for i in range(count)],
        "native_windows": [{"index": i} for i in range(count)],
        "paid_recovery": True,
        "world_elapsed_seconds": elapsed if count == 2 else 1300.,
        "minimum_native_actor_health": health,
        "gsim_route_paid_movement_s": 8. if count == 2 else 300.,
        "gsim_route_paid_receipts": [{} for _ in range(count - 1)],
        "native_passive_recovery_observed": True,
        "native_passive_recovery_ns_by_target": [0] + [24_000_000_000] * (count - 1),
    }


def test_candidate_orders_only_original_actions_and_preserves_source():
    source = fixture()
    candidates = _source_apl_candidates(source)
    assert [name for name, _ in candidates] == [
        "source", "advance_last", "advance_penultimate",
    ]
    assert [policy_label(request) for _, request in candidates] == [
        "source", "advance_last", "advance_penultimate",
    ]
    assert source == fixture()
    for _, candidate in candidates:
        assert sorted(
            json.dumps(action, sort_keys=True)
            for action in candidate["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
        ) == sorted(
            json.dumps(action, sort_keys=True)
            for action in source["raid"]["parties"][0]["players"][0]["rotation"]["priorityList"]
        )


def test_native_two_target_survival_selects_one_genuine_100_target_run(tmp_path):
    path = write_source(tmp_path)
    called = []
    def world(binary, prepared, **kwargs):
        called.append((json.loads(prepared.read_text())["policy"], kwargs["target_count"]))
        return native_world(binary, prepared, **kwargs)
    result = search_feral_native_apl_survival(
        "/native", path, prepare_run=native_prepare, world_run=world,
    )
    assert called == [
        ("source", 2), ("advance_last", 2),
        ("advance_penultimate", 2), ("advance_last", 100),
    ]
    assert result["selected_policy"] == "advance_last"
    assert result["native_paid_100_target_objective"]["targets"] == 100
    assert result["native_paid_100_target_objective"]["mean_seconds_per_mob"] == 13.
    assert result["p4_p5_p6_certified"] is False
    assert json.loads(path.read_text()) == fixture()


def test_no_changed_native_health_or_time_gain_skips_100(tmp_path):
    path = write_source(tmp_path)
    counts = []
    def slow_world(binary, prepared, **kwargs):
        counts.append(kwargs["target_count"])
        result = native_world(binary, prepared, **kwargs)
        if json.loads(prepared.read_text())["policy"] != "source":
            result["minimum_native_actor_health"] = 30.
        return result
    with pytest.raises(RuntimeError, match="NO_MEASURED_TWO_TARGET_IMPROVEMENT"):
        search_feral_native_apl_survival(
            "/native", path, prepare_run=native_prepare, world_run=slow_world,
        )
    assert counts == [2, 2, 2]


def test_native_refusals_cannot_win_or_trigger_100(tmp_path):
    path = write_source(tmp_path)
    def reject_changed(argv, **kwargs):
        request = json.loads(open(argv[3], encoding="utf-8").read())
        if policy_label(request) != "source":
            raise subprocess.CalledProcessError(3, argv, stderr="INVALID: APL")
        native_prepare(argv, **kwargs)
    with pytest.raises(RuntimeError, match="NO_MEASURED_TWO_TARGET_IMPROVEMENT") as exc:
        search_feral_native_apl_survival(
            "/native", path, prepare_run=reject_changed, world_run=native_world,
        )
    assert "INVALID: APL" in str(exc.value)


def test_selected_native_100_target_death_not_scored(tmp_path):
    path = write_source(tmp_path)
    def lethal(binary, prepared, **kwargs):
        if kwargs["target_count"] == 100:
            raise AssertionError(
                "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=44:"
                "adjacent_native_windows=[]"
            )
        return native_world(binary, prepared, **kwargs)
    with pytest.raises(RuntimeError, match="FERAL_NATIVE_APL_100_TARGET_NATIVE_DEATH") as exc:
        search_feral_native_apl_survival(
            "/native", path, prepare_run=native_prepare, world_run=lethal,
        )
    assert '"first' not in str(exc.value) or "first_index=44" in str(exc.value)
    assert "advance_last" in str(exc.value)


@pytest.mark.parametrize("seconds", [0, 121, 1.0, True])
def test_invalid_recovery_cannot_be_forwarded(tmp_path, seconds):
    with pytest.raises(ValueError, match="RECOVERY_SECONDS_INVALID"):
        search_feral_native_apl_survival(
            "/native", tmp_path / "absent", recovery_seconds=seconds,
        )
