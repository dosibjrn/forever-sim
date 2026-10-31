from __future__ import annotations
from math import isclose
import pytest
from src.shared.leveling.spaced_pulls import SpacedPullLayout


def test_three_mobs_square_grid_not_prepacked():
    p=SpacedPullLayout(3,20,7)
    assert p.positions_yards[0] == (0., 0.)
    assert p.positions_yards[1] == (20., 0.)
    assert p.positions_yards[2][1] > 0
    for i,j in ((0,1),(1,2)):
        assert p.distance_yards(i,j) == pytest.approx(20)
    assert p.distance_yards(0,2) == pytest.approx(20 * 2 ** .5)
    assert p.initial_melee_targets() == (0,)
    assert p.targets_in_melee(p.positions_yards[2]) == (2,)
    assert p.minimum_walk_to_tag_farthest_s == pytest.approx(30/7)
    assert p.sequential_travel_total_s == pytest.approx(40/7)
    assert p.as_dict()['simultaneous_pack_assembled'] is False


def test_ring_2_has_no_closer_than_20yd_neighbors():
    p=SpacedPullLayout(19,20)
    assert any(abs(y)>1 for x,y in p.positions_yards)
    for i in range(19):
        for j in range(i+1,19):
            assert p.distance_yards(i,j) >= 20-1e-8


def test_stacked_mobs_have_no_spatial_cost_and_are_in_range():
    p=SpacedPullLayout(3,0)
    assert p.initial_melee_targets()==(0,1,2)
    assert p.sequential_travel_total_s==0


def test_invalid_spaced_pull_layout_fails_closed():
    for v in (-1,float('nan'),float('inf')):
        with pytest.raises(ValueError):SpacedPullLayout(3,v)
    for p in ((float('nan'),1), (1,), (0,float('inf'))):
        with pytest.raises(ValueError):SpacedPullLayout(3).targets_in_melee(p)
