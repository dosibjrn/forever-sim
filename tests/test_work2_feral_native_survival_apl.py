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
    assert kwargs["native_recovery_seconds"] in (24, 120)
    assert kwargs["rng_mode"] == "balanced"
    label = json.loads(prepared.read_text())["policy"]
    count = kwargs["target_count"]
    # All selected scores are source-native observations, not Python combat.
    health = {"source": 40., "advance_last": 85.,
              "advance_penultimate": 70.}[label]
    elapsed = {"source": 18., "advance_last": 15.,
               "advance_penultimate": 13.}[label]
    if count in (50, 100) and label == "source":
        raise AssertionError("Unexpected expensive replay")
    return {
        "continuous_native_actor": True,
        "actual_2d_ack": True,
        "world_targets_killed": count,
        "world_kills": [{"target_id": str(i)} for i in range(count)],
        "native_windows": [{"index": i} for i in range(count)],
        "paid_recovery": True,
        "world_elapsed_seconds": elapsed if count == 2 else 1300.,
        # Only selected-native observations set this score. Longer paid
        # recovery can preserve actor health across a sustained 50-mob pull.
        "minimum_native_actor_health": (
            health + 70. if count == 50 and kwargs["native_recovery_seconds"] == 120
            else health
        ),
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
        called.append((json.loads(prepared.read_text())["policy"],
                       kwargs["target_count"], kwargs["native_recovery_seconds"]))
        return native_world(binary, prepared, **kwargs)
    result = search_feral_native_apl_survival(
        "/native", path, prepare_run=native_prepare, world_run=world,
    )
    assert called == [
        ("source", 2, 24), ("advance_last", 2, 24),
        ("advance_penultimate", 2, 24), ("advance_last", 50, 24),
        ("advance_last", 50, 120), ("advance_last", 100, 120),
    ]
    assert result["selected_policy"] == "advance_last"
    assert result["selected_recovery_seconds"] == 120
    assert result["failed_native_100_target_attempts"] == []
    assert [(r["screen_targets"], r["recovery_seconds"], r["status"])
            for r in result["recovery_screens"]] == [
        (50, 24, "native_screen_survived"),
        (50, 120, "native_screen_survived"),
    ]
    assert result["native_paid_100_target_objective"]["targets"] == 100
    assert result["native_paid_100_target_objective"]["mean_seconds_per_mob"] == 13.
    assert result["p4_p5_p6_certified"] is False
    assert json.loads(path.read_text()) == fixture()


def test_weaker_two_target_native_policy_can_survive_long_world(tmp_path):
    """Two-target HP is a sort key, not an invented 50/100-mob veto."""
    path = write_source(tmp_path)
    counts = []

    def slow_world(binary, prepared, **kwargs):
        counts.append(kwargs["target_count"])
        result = native_world(binary, prepared, **kwargs)
        if json.loads(prepared.read_text())["policy"] != "source":
            result["minimum_native_actor_health"] = 30.
        return result

    result = search_feral_native_apl_survival(
        "/native", path, prepare_run=native_prepare, world_run=slow_world,
    )
    assert counts == [2, 2, 2, 50, 50, 100]
    assert result["two_target_screens"][0]["minimum_native_actor_health"] == 40.
    assert result["selected_native_two_target_screen"]["minimum_native_actor_health"] == 30.
    assert result["native_paid_100_target_objective"]["targets"] == 100


def test_dead_source_two_target_screen_does_not_veto_native_survivor(tmp_path):
    """A failed old APL must not pre-veto an independently viable new APL."""
    path = write_source(tmp_path)
    calls = []

    def dead_source(binary, prepared, **kwargs):
        policy = json.loads(prepared.read_text())["policy"]
        count = kwargs["target_count"]
        calls.append((policy, count))
        if policy == "source" and count == 2:
            raise AssertionError(
                "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=1:"
                "adjacent_native_windows=[]"
            )
        return native_world(binary, prepared, **kwargs)

    result = search_feral_native_apl_survival(
        "/native", path, prepare_run=native_prepare, world_run=dead_source,
    )
    assert result["two_target_screens"][0]["status"] == "native_refused_or_dead"
    assert result["selected_policy"] == "advance_last"
    assert sum(count == 100 for _, count in calls) == 1
    assert result["native_paid_100_target_objective"]["targets"] == 100


def test_native_refusals_cannot_win_or_trigger_100(tmp_path):
    path = write_source(tmp_path)
    def reject_changed(argv, **kwargs):
        request = json.loads(open(argv[3], encoding="utf-8").read())
        if policy_label(request) != "source":
            raise subprocess.CalledProcessError(3, argv, stderr="INVALID: APL")
        native_prepare(argv, **kwargs)
    with pytest.raises(RuntimeError, match="NO_EXECUTABLE_TWO_TARGET_ALTERNATIVE") as exc:
        search_feral_native_apl_survival(
            "/native", path, prepare_run=reject_changed, world_run=native_world,
        )
    assert "INVALID: APL" in str(exc.value)


def test_selected_native_100_target_death_not_scored(tmp_path):
    path = write_source(tmp_path)
    tried_hundred = []

    def lethal(binary, prepared, **kwargs):
        if kwargs["target_count"] == 100:
            tried_hundred.append(json.loads(prepared.read_text())["policy"])
            raise AssertionError(
                "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=44:"
                "adjacent_native_windows=[]"
            )
        return native_world(binary, prepared, **kwargs)

    with pytest.raises(RuntimeError, match="FERAL_NATIVE_APL_100_TARGET_NATIVE_DEATH") as exc:
        search_feral_native_apl_survival(
            "/native", path, prepare_run=native_prepare, world_run=lethal,
        )
    assert tried_hundred == ["advance_last", "advance_penultimate"]
    assert "first_index=44" in str(exc.value)
    assert all(policy in str(exc.value) for policy in tried_hundred)


def test_native_hundred_death_falls_back_to_next_paid_fifty_survivor(tmp_path):
    """The first policy dying after mob 50 must not veto another real survivor."""
    path = write_source(tmp_path)
    calls = []

    def first_dies(binary, prepared, **kwargs):
        policy = json.loads(prepared.read_text())["policy"]
        count = kwargs["target_count"]
        rest = kwargs["native_recovery_seconds"]
        calls.append((policy, count, rest))
        if policy == "advance_last" and count == 100:
            raise AssertionError(
                "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=72:"
                "adjacent_native_windows=[]"
            )
        return native_world(binary, prepared, **kwargs)

    result = search_feral_native_apl_survival(
        "/native", path, prepare_run=native_prepare, world_run=first_dies,
    )
    assert calls == [
        ("source", 2, 24),
        ("advance_last", 2, 24),
        ("advance_penultimate", 2, 24),
        ("advance_last", 50, 24),
        ("advance_last", 50, 120),
        ("advance_last", 100, 120),
        ("advance_penultimate", 50, 24),
        ("advance_penultimate", 50, 120),
        ("advance_penultimate", 100, 120),
    ]
    assert result["selected_policy"] == "advance_penultimate"
    assert result["selected_recovery_seconds"] == 120
    assert result["native_paid_100_target_objective"]["targets"] == 100
    assert result["failed_native_100_target_attempts"] == [{
        "selected_policy": "advance_last",
        "selected_recovery_seconds": 120,
        "native_failure": (
            "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=72:"
            "adjacent_native_windows=[]"),
        "native_prepared_request_sha256": "a" * 64,
    }]
    assert result["p4_p5_p6_certified"] is False


@pytest.mark.parametrize("seconds", [0, 121, 1.0, True])
def test_invalid_recovery_cannot_be_forwarded(tmp_path, seconds):
    with pytest.raises(ValueError, match="RECOVERY_SECONDS_INVALID"):
        search_feral_native_apl_survival(
            "/native", tmp_path / "absent", recovery_seconds=seconds,
        )


def test_native_fifty_target_death_selects_surviving_longer_rest(tmp_path):
    """The documented mob-50 death must not discard a surviving native rest."""
    path = write_source(tmp_path)
    calls = []

    def recovering_world(binary, prepared, **kwargs):
        calls.append((kwargs["target_count"], kwargs["native_recovery_seconds"]))
        if kwargs["target_count"] == 50 and kwargs["native_recovery_seconds"] == 24:
            raise AssertionError(
                "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=49:"
                'adjacent_native_windows=[{"actor_health":0}]'
            )
        return native_world(binary, prepared, **kwargs)

    result = search_feral_native_apl_survival(
        "/native", path, prepare_run=native_prepare, world_run=recovering_world,
    )
    assert calls[-3:] == [(50, 24), (50, 120), (100, 120)]
    assert result["recovery_screens"][0]["status"] == "native_actor_died"
    assert "first_index=49" in result["recovery_screens"][0]["native_failure"]
    assert result["recovery_screens"][1]["status"] == "native_screen_survived"
    assert result["selected_recovery_seconds"] == 120
    assert result["native_paid_100_target_objective"]["targets"] == 100


def test_no_native_survivor_at_fifty_never_pays_hundred(tmp_path):
    """Two genuine native deaths are rejections, not fabricated 100-mob scores."""
    path = write_source(tmp_path)
    calls = []

    def lethal_world(binary, prepared, **kwargs):
        calls.append(kwargs["target_count"])
        if kwargs["target_count"] == 50:
            raise AssertionError(
                "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=40:"
                "adjacent_native_windows=[]"
            )
        if kwargs["target_count"] == 100:
            raise AssertionError("100-mob should not be run")
        return native_world(binary, prepared, **kwargs)

    with pytest.raises(RuntimeError, match="NO_SURVIVING_RECOVERY_SCREEN") as exc:
        search_feral_native_apl_survival(
            "/native", path, prepare_run=native_prepare, world_run=lethal_world,
        )
    assert calls == [2, 2, 2, 50, 50, 50, 50]
    assert '"native_actor_died"' in str(exc.value)


def test_recovery_screen_does_not_hide_native_ack_transport_failure(tmp_path):
    """Only an actual native death is rejectable; ACK errors remain fatal."""
    path = write_source(tmp_path)

    def broken_world(binary, prepared, **kwargs):
        if kwargs["target_count"] == 50:
            raise AssertionError("RUST_TWO_WORLD_CLOCK_SOURCE_OR_SEQUENCE_INVALID")
        return native_world(binary, prepared, **kwargs)

    with pytest.raises(AssertionError, match="RUST_TWO_WORLD_CLOCK_SOURCE_OR_SEQUENCE_INVALID"):
        search_feral_native_apl_survival(
            "/native", path, prepare_run=native_prepare, world_run=broken_world,
        )


def test_lethal_two_target_winner_falls_back_to_next_native_apl(tmp_path):
    """A real 50-mob death cannot veto the next independently paid APL."""
    path = write_source(tmp_path)
    calls = []

    def fallback_world(binary, prepared, **kwargs):
        policy = json.loads(prepared.read_text())["policy"]
        count = kwargs["target_count"]
        rest = kwargs["native_recovery_seconds"]
        calls.append((policy, count, rest))
        if count == 50 and policy == "advance_last":
            raise AssertionError(
                "RUST_MULTI_WORLD_NATIVE_ACTOR_NOT_ALIVE:first_index=49:"
                "adjacent_native_windows=[]"
            )
        return native_world(binary, prepared, **kwargs)

    result = search_feral_native_apl_survival(
        "/native", path, prepare_run=native_prepare, world_run=fallback_world,
    )
    assert calls == [
        ("source", 2, 24),
        ("advance_last", 2, 24),
        ("advance_penultimate", 2, 24),
        ("advance_last", 50, 24),
        ("advance_last", 50, 120),
        ("advance_penultimate", 50, 24),
        ("advance_penultimate", 50, 120),
        ("advance_penultimate", 100, 120),
    ]
    assert result["selected_policy"] == "advance_penultimate"
    assert result["selected_recovery_seconds"] == 120
    assert result["native_paid_100_target_objective"]["targets"] == 100
    assert [entry["policy"] for entry in result["recovery_screens"]] == [
        "advance_last", "advance_last",
        "advance_penultimate", "advance_penultimate",
    ]
    assert [entry["status"] for entry in result["recovery_screens"]] == [
        "native_actor_died", "native_actor_died",
        "native_screen_survived", "native_screen_survived",
    ]
    assert json.loads(path.read_text()) == fixture()
