from __future__ import annotations
import unittest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.analytic_scorer import AnalyticOptions
from src.v2.local_search import search_level_analytic
from src.v2.parallel_search import search_levels_parallel

class ParallelAnalyticPathTests(unittest.TestCase):
    def test_search_level_analytic_returns_scored_nodes(self):
        cfg=eng.SimConfig(use_best_water=True)
        rows=search_level_analytic(20,cfg,options=AnalyticOptions(kill_boundary_model='hard'),
                                   beam_width=8,family_keep=1,final_k=5)
        self.assertTrue(rows)
        self.assertTrue(all(r.level==20 and r.talents.points()==11 for r in rows))
        self.assertTrue(all(r.policy is not None for r in rows))

    def test_parallel_two_levels(self):
        cfg=eng.SimConfig(use_best_water=True)
        pools=search_levels_parallel([19,20],cfg,options=AnalyticOptions(kill_boundary_model='hard'),
                                     beam_width=6,family_keep=1,final_k=4,max_workers=2)
        self.assertEqual(set(pools),{19,20})
        self.assertTrue(all(pools[l] for l in pools))

if __name__=='__main__': unittest.main()
