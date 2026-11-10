from __future__ import annotations

"""Native paid route continuity uses Rust-prepared edges, not Python talent rules."""

import pytest

from src.v2.path_dp import LevelNode, solve_path_dp


def _native(level, marker, score, talents):
    return LevelNode(
        level, talents, score,
        source="native_paid_100_mob",
        details={"source_request_sha256": marker * 64},
    )


def test_native_banked_l21_then_spent_l22_with_real_request_edges():
    l20 = _native(20, "a", 1800, "prepared_L20")
    l21 = _native(21, "b", 1600, "prepared_L20")  # bank one point
    l22 = _native(22, "c", 1500, "prepared_L22")
    path = solve_path_dp(
        {20: [l20], 21: [l21], 22: [l22]},
        weights={20: 1, 21: 1, 22: 1},
        max_respecs=0,
        native_edges={
            ("a" * 64, "b" * 64): ("hold", None),
            ("b" * 64, "c" * 64): ("point", "Ruin"),
        },
    )
    assert [step.kind for step in path.steps] == ["start", "hold", "point"]
    assert [step.talent_added for step in path.steps] == [None, None, "Ruin"]
    assert path.cumulative_s == 4900
    assert path.resolved_through_level == 22


def test_native_refused_or_missing_edge_never_becomes_a_route():
    a = _native(20, "a", 1800, "L20")
    b = _native(21, "b", 1600, "L21")
    with pytest.raises(ValueError, match="no legal path"):
        solve_path_dp({20: [a], 21: [b]}, max_respecs=0,
                      weights={20: 1, 21: 1}, native_edges={})


def test_native_equipped_alternatives_are_not_deduplicated_by_talents():
    a = _native(20, "a", 1800, "L20")
    b = _native(20, "b", 1650, "L20")
    c = _native(21, "c", 1700, "L20")
    path = solve_path_dp(
        {20: [a, b], 21: [c]}, weights={20: 1, 21: 1}, max_respecs=0,
        native_edges={("a" * 64, "c" * 64): ("hold", None)},
    )
    assert path.steps[0].node.details["source_request_sha256"] == "a" * 64


def test_native_route_rejects_unprepared_respec_and_untrusted_ids():
    a = _native(20, "a", 1800, "L20")
    b = _native(21, "b", 1700, "L20")
    with pytest.raises(ValueError, match="native route respec"):
        solve_path_dp({20: [a], 21: [b]}, native_edges={})
    with pytest.raises(ValueError, match="source_request_sha256"):
        solve_path_dp({20: [LevelNode(20, "L20", 1800)]},
                      max_respecs=0, native_edges={})
    with pytest.raises(ValueError, match="malformed native-prepared"):
        solve_path_dp({20: [a], 21: [b]}, max_respecs=0,
                      native_edges={("a" * 64, "b" * 64): ("hold", "not-a-point")})


def test_legacy_analytical_full_spend_gate_is_unchanged():
    class LegacyModel:
        def build_key(self, talents): return talents
        def build_points(self, talents): return talents
        def build_preference_key(self, talents): return talents
        def policy_description(self, policy, level): return ""
        def legal_one_point_transition(self, parent, child):
            return "point" if child == parent + 1 else None

    with pytest.raises(ValueError, match="expected 12"):
        solve_path_dp(
            {20: [LevelNode(20, 11, 1)], 21: [LevelNode(21, 11, 1)]},
            max_respecs=0, model=LegacyModel(), weights={20: 1, 21: 1},
        )
