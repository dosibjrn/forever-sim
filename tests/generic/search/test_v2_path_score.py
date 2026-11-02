from __future__ import annotations
import unittest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.path_score import score_path_levels

class PathScoreTests(unittest.TestCase):
    def test_levels_are_independent_and_reduce(self):
        cfg=eng.SimConfig(use_best_water=True)
        alloc={20:eng.Talents(imp_frostbolt=5,elemental_precision=3),21:eng.Talents(imp_frostbolt=5,elemental_precision=3,ice_shards=1)}
        r=score_path_levels(alloc,cfg,max_workers=1,weights={20:2,21:3})
        self.assertEqual([x.level for x in r.levels],[20,21])
        self.assertAlmostEqual(r.weighted_score,2*r.levels[0].seconds_per_100+3*r.levels[1].seconds_per_100)
if __name__=='__main__': unittest.main()


def test_tied_dp_path_prefers_arcane_subtlety_over_synthetic_arcane_filler():
    from src.v2.path_dp import LevelNode, solve_path_dp
    p=eng.Policy('FBo','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
    # Two legal lvl11 starts with identical modeled score. The real utility
    # talent should win the deterministic tie over synthetic filler.
    subtle=eng.Talents(arcane_subtlety=2)
    filler=eng.Talents(arcane_filler=2)
    pools={11:[LevelNode(11,filler,100.0,p,'smooth',{}),LevelNode(11,subtle,100.0,p,'smooth',{})]}
    got=solve_path_dp(pools,max_respecs=0,start_level=11,end_level=11,weights={11:1.0})
    assert got.steps[0].node.talents.arcane_subtlety==2
    assert got.steps[0].node.talents.arcane_filler==0
