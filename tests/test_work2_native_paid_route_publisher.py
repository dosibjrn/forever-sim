"""Source-native Warlock paid route continuity is evidence, not a new gate."""
from __future__ import annotations

from tools.wf_warlock_route_guide import build_route_report, render_guide


def observation(level: int, talents: str, *, actor=True, status=None):
    row = {
        "id": f"real-native-l{level}", "level": level,
        "trial": f"paid-source-native-l{level}",
        "candidate": f"L{level} native actor", "scenario": f"hostile L{level}",
        "targets_requested": 100, "targets_killed": 100,
        "seconds_per_mob": 14.0,
        "paid_native_recovery": True, "native_world_ack": True,
        "run_url": f"https://github.com/dosibjrn/forever-sim/actions/runs/{level}",
        "engine_binary_sha256": "b" * 64,
        "source_request_sha256": "a" * 64,
        "talents": talents,
        "gear": [{"id": 101}], "apl": [], "pet": None,
        "pulls": None, "recovery_policy": {"recovery_policy": "decisions"},
    }
    if actor:
        row["native_actor"] = {"class": "ClassWarlock", "level": level}
    if status is not None:
        row["status"] = status
    return row


def report(*rows):
    return build_route_report({
        "schema_version": 1, "class": "warlock",
        "start_level": 10, "end_level": 60,
        "observations": list(rows),
    })


def test_measured_l20_l21_banked_hold_flows_into_route_json_and_guide():
    l20 = "0-0-11111111111"
    result = report(
        observation(20, l20),
        observation(21, l20),
        observation(22, "0-0-111111111111"))
    path = result["native_paid_talent_continuity"]
    assert path["status"] == "connected_native_paid_talent_frontier"
    assert path["levels"] == [20, 21, 22]
    assert [step["kind"] for step in path["steps"]] == ["start", "hold", "point"]
    assert path["steps"][1]["native_observation_id"] == "real-native-l21"
    assert path["xp_progression_simulated"] is False
    assert path["cumulative_leveling_seconds"] is None
    assert result["full_10_60_native_replay_executed"] is False
    assert "L21: hold" in render_guide(result)


def test_without_actual_native_prepared_actor_no_path_is_inferred():
    l20 = "0-0-11111111111"
    result = report(observation(20, l20), observation(21, l20, actor=False))
    path = result["native_paid_talent_continuity"]
    assert path["status"] == "single_native_paid_level"
    assert path["levels"] == [20]
    assert result["measured_levels"] == [20, 21]
    assert result["full_10_60_native_replay_executed"] is False


def test_changed_engine_is_not_silently_merged_into_same_native_path():
    l20 = observation(20, "0-0-11111111111")
    l21 = observation(21, "0-0-11111111111")
    l21["engine_binary_sha256"] = "c" * 64
    path = report(l20, l21)["native_paid_talent_continuity"]
    assert path["levels"] == [20]
    assert path["status"] == "single_native_paid_level"
