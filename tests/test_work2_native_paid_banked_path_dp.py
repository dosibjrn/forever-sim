"""Paid native route-frontier regression; never tests Rust talent/gameplay rules."""
from __future__ import annotations

from dataclasses import replace

import pytest

from src.v2.class_model import ClassModel
from src.v2.path_dp import LevelNode, solve_path_dp


class OpaqueNativeBuildModel(ClassModel):
    name = "native-receipt-test"

    def evaluate(self, ctx):
        raise AssertionError("paid native scores must be passed to route DP")

    def build_key(self, build):
        return tuple(build)

    def build_points(self, build):
        return len(build)

    def legal_one_point_transition(self, parent, child):
        # Test-only opaque transition hook, not a game-rule implementation.
        if len(child) == len(parent) + 1 and tuple(child[:-1]) == tuple(parent):
            return str(child[-1])
        return None


def paid_node(level, build, cost):
    receipt = {
        "status": "measured_native_chain", "level": level,
        "native_actor": {"class": "ClassWarlock", "level": level},
        "native_world_ack": True, "paid_native_recovery": True,
        "targets_requested": 100, "targets_killed": 100,
        "source_request_sha256": "a" * 64, "engine_binary_sha256": "b" * 64,
    }
    return LevelNode(level, tuple(build), cost, source="native_paid",
                     details={"native_receipt": receipt})


def test_real_paid_l20_to_l21_bank_is_reachable_without_spending_or_respec():
    initial = tuple("abcdefghijk")  # 11 invested ranks at L20
    pools = {
        20: [paid_node(20, initial, 18.0)],
        21: [paid_node(21, initial, 17.0)],  # bank the L21 point
        22: [paid_node(22, initial + ("l",), 16.0)],
    }
    result = solve_path_dp(
        pools, max_respecs=0, weights={20: 1.0, 21: 1.0, 22: 1.0},
        model=OpaqueNativeBuildModel(), native_paid=True)
    assert [step.kind for step in result.steps] == ["start", "hold", "point"]
    assert [step.talent_added for step in result.steps] == [None, None, "l"]
    assert result.respecs_used == 0
    assert result.cumulative_s == 51.0


def test_analytic_dp_keeps_full_spend_contract_for_exact_same_input():
    build = tuple("abcdefghijk")
    pools = {20: [paid_node(20, build, 18.0)],
             21: [paid_node(21, build, 17.0)]}
    with pytest.raises(ValueError, match="expected 12"):
        solve_path_dp(pools, max_respecs=0, model=OpaqueNativeBuildModel())


@pytest.mark.parametrize("tamper", [
    lambda r: {**r, "status": "NATIVE_PREPARED_NOT_YET_PAID"},
    lambda r: {**r, "paid_native_recovery": False},
    lambda r: {**r, "native_world_ack": False},
    lambda r: {**r, "targets_killed": 99},
    lambda r: {**r, "native_actor": {"class": "ClassWarlock", "level": 22}},
    lambda r: {**r, "source_request_sha256": None},
])
def test_unmeasured_refused_or_wrong_actor_cannot_be_native_path(tamper):
    build = tuple("abcdefghijk")
    first = paid_node(20, build, 18.0)
    child = paid_node(21, build, 17.0)
    damaged = replace(child, details={
        "native_receipt": tamper(child.details["native_receipt"]),
    })
    with pytest.raises(ValueError, match="matching paid native actor"):
        solve_path_dp(
            {20: [first], 21: [damaged]},
            max_respecs=0, model=OpaqueNativeBuildModel(), native_paid=True)


def test_native_mode_does_not_launder_analytic_nodes_or_over_budget_points():
    build = tuple("abcdefghijk")
    paid = paid_node(20, build, 18.0)
    with pytest.raises(ValueError, match="matching paid native actor"):
        solve_path_dp(
            {20: [replace(paid, source="analytic")]},
            model=OpaqueNativeBuildModel(), native_paid=True)
    with pytest.raises(ValueError, match="impossible point count"):
        solve_path_dp(
            {20: [paid_node(20, build + ("z",), 18.0)]},
            model=OpaqueNativeBuildModel(), native_paid=True)


def test_native_route_defaults_to_no_unobserved_respec():
    initial = tuple("abcdefghijk")
    result = solve_path_dp(
        {20: [paid_node(20, initial, 18.0)],
         21: [paid_node(21, initial, 17.0)]},
        model=OpaqueNativeBuildModel(), native_paid=True)
    assert [step.kind for step in result.steps] == ["start", "hold"]
    assert result.respecs_used == 0


def test_native_route_rejects_respec_without_executed_native_edge():
    initial = tuple("abcdefghijk")
    with pytest.raises(ValueError, match="no prepared respec edges"):
        solve_path_dp(
            {20: [paid_node(20, initial, 18.0)]},
            max_respecs=1, model=OpaqueNativeBuildModel(),
            native_paid=True)


def test_native_route_mixed_binary_cannot_create_fake_continuity():
    initial = tuple("abcdefghijk")
    parent = paid_node(20, initial, 18.0)
    child = paid_node(21, initial, 17.0)
    altered = replace(child, details={
        "native_receipt": {
            **child.details["native_receipt"],
            "engine_binary_sha256": "c" * 64,
        },
    })
    with pytest.raises(ValueError, match="mixes engine binary identities"):
        solve_path_dp(
            {20: [parent], 21: [altered]},
            max_respecs=0, model=OpaqueNativeBuildModel(),
            native_paid=True)
