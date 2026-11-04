from __future__ import annotations

"""Regression for stable tie-breaking in the retained exact path DP."""

from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.path_dp import LevelNode, solve_path_dp


def test_tied_dp_path_prefers_arcane_subtlety_over_synthetic_arcane_filler():
    p = eng.Policy("FBo", "frostbolt", use_fireblast=False, use_nova=False, use_blink=False)
    subtle = eng.Talents(arcane_subtlety=2)
    filler = eng.Talents(arcane_filler=2)
    pools = {11: [
        LevelNode(11, filler, 100.0, p, "smooth", {}),
        LevelNode(11, subtle, 100.0, p, "smooth", {}),
    ]}
    got = solve_path_dp(pools, max_respecs=0, start_level=11, end_level=11, weights={11: 1.0})
    assert got.steps[0].node.talents.arcane_subtlety == 2
    assert got.steps[0].node.talents.arcane_filler == 0
