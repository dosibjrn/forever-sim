"""Source-native banked talent points are route data, not Python legality rules."""

import pytest

from src.v2.path_dp import LevelNode, solve_path_dp


class _OpaqueBuildModel:
    """Minimal route adapter: no Warcraft data or talent-rank implementation."""

    def build_key(self, build):
        return tuple(build)

    def build_points(self, build):
        return len(build)

    def legal_one_point_transition(self, parent, child):
        if len(child) == len(parent) + 1 and tuple(child[:-1]) == tuple(parent):
            return str(child[-1])
        return None

    def build_preference_key(self, build):
        return tuple(build)

    def policy_description(self, policy, level):
        return str(policy)


def _node(level, talents, score, *, paid=False):
    return LevelNode(
        level, tuple(talents), score, source="native_paid" if paid else "analytic",
        native_paid_prepared=paid,
    )


def _solve(pools):
    return solve_path_dp(
        pools, max_respecs=0, model=_OpaqueBuildModel(),
        weights={level: 1 for level in pools},
    )


def test_paid_native_l20_l21_bank_then_l22_spend_is_a_contiguous_route():
    l20 = tuple(range(11))
    l22 = (*l20, 99)
    route = _solve({
        20: [_node(20, l20, 10, paid=True)],
        21: [_node(21, l20, 9, paid=True)],
        22: [_node(22, l22, 8, paid=True)],
    })
    assert [(step.node.level, step.kind, step.talent_added) for step in route.steps] == [
        (20, "start", None), (21, "hold", None), (22, "point", "99"),
    ]
    assert route.respecs_used == 0
    assert route.cumulative_s == 27


def test_legacy_analytic_l21_unspent_build_is_still_rejected():
    talents = tuple(range(11))
    with pytest.raises(ValueError, match="level 21 node has 11 talent points"):
        _solve({
            20: [_node(20, talents, 10)],
            21: [_node(21, talents, 9)],
        })


def test_native_hold_requires_both_adjacent_observations_to_be_paid_prepared():
    talents = tuple(range(11))
    with pytest.raises(ValueError, match="no legal path reaches level 21"):
        _solve({
            20: [_node(20, talents, 10)],  # Analytic node is not a native receipt.
            21: [_node(21, talents, 9, paid=True)],
        })


def test_cheaper_analytic_candidate_cannot_displace_paid_native_hold_source():
    talents = tuple(range(11))
    route = _solve({
        20: [_node(20, talents, 1), _node(20, talents, 10, paid=True)],
        21: [_node(21, talents, 9, paid=True)],
    })
    assert route.cumulative_s == 19
    assert route.steps[0].node.native_paid_prepared is True
    assert route.steps[-1].kind == "hold"


def test_native_paid_point_bank_does_not_legalize_extra_or_multiple_points():
    talents = tuple(range(11))
    with pytest.raises(ValueError, match="level 21 node has 13 talent points"):
        _solve({
            20: [_node(20, talents, 10, paid=True)],
            21: [_node(21, (*talents, 90, 91), 9, paid=True)],
        })
    with pytest.raises(ValueError, match="no legal path reaches level 22"):
        _solve({
            21: [_node(21, talents, 9, paid=True)],
            22: [_node(22, (*talents, 90, 91), 8, paid=True)],
        })


def test_native_and_analytic_scores_cannot_be_spliced_across_a_point_edge():
    talents = tuple(range(11))
    with pytest.raises(ValueError, match="no legal path reaches level 21"):
        _solve({
            20: [_node(20, talents, 10, paid=True)],
            21: [_node(21, (*talents, 90), 1)],  # Cheap but unmeasured proposal.
        })


def test_native_and_analytic_scores_cannot_be_spliced_by_respec():
    talents = tuple(range(11))
    with pytest.raises(ValueError, match="no legal path reaches level 21"):
        solve_path_dp(
            {
                20: [_node(20, talents, 10, paid=True)],
                21: [_node(21, (*talents, 90), 1)],
            },
            max_respecs=1, model=_OpaqueBuildModel(), weights={20: 1, 21: 1},
        )
