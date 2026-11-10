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


def _engine_observation(level: int, talents: str, engine: str) -> dict:
    row = observation(level, talents)
    row["id"] = f"native-{engine}-l{level}"
    row["engine_binary_sha256"] = engine * 64
    return row


def test_frontier_selects_longest_real_single_engine_prefix():
    l20 = "0-0-11111111111"
    # Both binaries paid the starting level; lexicographic 'a' ends there,
    # while 'b' supplies a genuine contiguous banked/spent progression.
    path = report(
        _engine_observation(20, l20, "a"),
        _engine_observation(20, l20, "b"),
        _engine_observation(21, l20, "b"),
        _engine_observation(22, "0-0-111111111111", "b"),
    )["native_paid_talent_continuity"]
    assert path["status"] == "connected_native_paid_talent_frontier"
    assert path["engine_binary_sha256"] == "b" * 64
    assert path["levels"] == [20, 21, 22]
    assert [step["kind"] for step in path["steps"]] == ["start", "hold", "point"]
    assert [step["native_observation_id"] for step in path["steps"]] == [
        "native-b-l20", "native-b-l21", "native-b-l22"]


def test_disconnected_paid_candidate_does_not_hide_another_engine_path():
    l20 = "0-0-11111111111"
    path = report(
        _engine_observation(20, l20, "a"),
        # The 'a' actor was paid, but its allocation cannot descend from
        # the selected 'a' L20 allocation without an unexecuted respec.
        _engine_observation(21, "0-0-11111111110", "a"),
        _engine_observation(20, l20, "b"),
        _engine_observation(21, l20, "b"),
    )["native_paid_talent_continuity"]
    assert path["status"] == "connected_native_paid_talent_frontier"
    assert path["engine_binary_sha256"] == "b" * 64
    assert path["levels"] == [20, 21]
    assert path["steps"][1]["native_observation_id"] == "native-b-l21"


def test_disconnected_native_binary_retains_proven_start_not_false_respec():
    l20 = "0-0-11111111111"
    path = report(
        _engine_observation(20, l20, "a"),
        _engine_observation(21, "0-0-11111111110", "a"),
    )["native_paid_talent_continuity"]
    assert path["status"] == "single_native_paid_level"
    assert path["levels"] == [20]
    assert path["steps"][0]["native_observation_id"] == "native-a-l20"


def test_incomplete_paid_candidate_does_not_discard_valid_same_level_path():
    l20 = "0-0-11111111111"
    incomplete = observation(21, l20)
    incomplete["id"] = "l21-missing-executed-request-identity"
    # A linked Actions result may be publishable as a measured snapshot even
    # when it lacks the exact source SHA required for talent lineage.
    incomplete["source_request_sha256"] = None
    valid = observation(21, l20)
    valid["id"] = "l21-fully-attributed"
    path = report(observation(20, l20), incomplete, valid)[
        "native_paid_talent_continuity"]
    assert path["levels"] == [20, 21]
    assert path["steps"][1]["kind"] == "hold"
    assert path["steps"][1]["native_observation_id"] == "l21-fully-attributed"


def test_incomplete_first_level_candidate_cannot_hide_other_paid_engine():
    l20 = "0-0-11111111111"
    incomplete = _engine_observation(20, l20, "a")
    incomplete["source_request_sha256"] = None
    path = report(
        incomplete,
        _engine_observation(20, l20, "b"),
        _engine_observation(21, l20, "b"),
    )["native_paid_talent_continuity"]
    assert path["engine_binary_sha256"] == "b" * 64
    assert path["levels"] == [20, 21]
    assert all(step["native_observation_id"].startswith("native-b-")
               for step in path["steps"])


def test_missing_prepared_l20_exposes_l21_l22_paid_interior_without_fake_start():
    """Source-paid interior is useful, but does not establish an L20 edge."""
    l20 = observation(20, "0-0-11111111111", actor=False)
    l21 = observation(21, "0-0-11111111111")
    l22 = observation(22, "0-0-111111111111")
    result = report(l20, l21, l22)
    path = result["native_paid_talent_continuity"]
    assert path["status"] == "interior_native_paid_talent_frontier"
    assert path["requested_start_level"] == 20
    assert path["observed_start_level"] == 21
    assert path["missing_preceding_levels"] == [20]
    assert path["levels"] == [21, 22]
    assert [step["kind"] for step in path["steps"]] == ["start", "point"]
    assert result["measured_levels"] == [20, 21, 22]
    assert result["full_10_60_native_replay_executed"] is False
    assert "No native-prepared link from L20" in render_guide(result)


def test_paid_interior_never_stitches_different_engine_binaries():
    l20 = observation(20, "0-0-11111111111", actor=False)
    l21 = _engine_observation(21, "0-0-11111111111", "a")
    l22 = _engine_observation(22, "0-0-111111111111", "b")
    path = report(l20, l21, l22)["native_paid_talent_continuity"]
    assert path["status"] == "single_interior_native_paid_level"
    assert path["levels"] == [21]
    assert path["engine_binary_sha256"] == "a" * 64
    assert path["missing_preceding_levels"] == [20]


def test_no_prepared_native_paid_actor_still_has_no_talent_lineage():
    l20 = observation(20, "0-0-11111111111", actor=False)
    l21 = observation(21, "0-0-11111111111", actor=False)
    path = report(l20, l21)["native_paid_talent_continuity"]
    assert path["status"] == "no_native_prepared_paid_start"
    assert path["levels"] == []


def test_paid_isolated_l20_does_not_hide_longer_different_binary_interior():
    """A new L20 native actor cannot erase already genuine L21+ continuity."""
    l20 = _engine_observation(20, "0-0-11111111111", "a")
    l21 = _engine_observation(21, "0-0-11111111111", "b")
    l22 = _engine_observation(22, "0-0-111111111111", "b")
    l23 = _engine_observation(23, "0-0-1111111111111", "b")
    result = report(l20, l21, l22, l23)
    path = result["native_paid_talent_continuity"]
    assert path["status"] == "interior_native_paid_talent_frontier"
    assert path["levels"] == [21, 22, 23]
    assert path["engine_binary_sha256"] == "b" * 64
    assert path["requested_start_level"] == 20
    assert path["observed_start_level"] == 21
    assert path["missing_preceding_levels"] == [20]
    assert result["measured_levels"] == [20, 21, 22, 23]
    assert result["full_10_60_native_replay_executed"] is False
    assert "No native-prepared link from L20" in render_guide(result)


def test_real_gap_does_not_hide_later_longer_same_binary_segment():
    """Never jump a missing L22, but publish genuinely connected L23-25."""
    l20 = _engine_observation(20, "0-0-11111111111", "b")
    l21 = _engine_observation(21, "0-0-11111111111", "b")
    l23 = _engine_observation(23, "0-0-1111111111111", "b")
    l24 = _engine_observation(24, "0-0-11111111111111", "b")
    l25 = _engine_observation(25, "0-0-111111111111111", "b")
    path = report(l20, l21, l23, l24, l25)["native_paid_talent_continuity"]
    assert path["status"] == "interior_native_paid_talent_frontier"
    assert path["levels"] == [23, 24, 25]
    assert path["observed_start_level"] == 23
    assert path["missing_preceding_levels"] == [20, 21, 22]
    assert [step["kind"] for step in path["steps"]] == ["start", "point", "point"]


def test_equal_length_paid_segments_prefer_earliest_observed_start():
    path = report(
        _engine_observation(20, "0-0-11111111111", "b"),
        _engine_observation(21, "0-0-11111111111", "b"),
        _engine_observation(23, "0-0-1111111111111", "a"),
        _engine_observation(24, "0-0-11111111111111", "a"),
    )["native_paid_talent_continuity"]
    assert path["status"] == "connected_native_paid_talent_frontier"
    assert path["levels"] == [20, 21]
    assert path["engine_binary_sha256"] == "b" * 64
