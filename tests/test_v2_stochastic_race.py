from __future__ import annotations
import unittest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.analytic_scorer import score_policy_analytic
from src.v2.stochastic_diagnostics import Candidate
from src.v2.stochastic_race import race_candidates

class StochasticRaceTests(unittest.TestCase):
    def test_race_extends_with_bounded_work(self):
        cfg=eng.SimConfig(use_best_water=True,root_break_mode='scaled')
        p=eng.Policy('pure','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
        ts=[eng.Talents(imp_frostbolt=5,elemental_precision=x) for x in (1,2,3)]
        cs=[Candidate(t,p,score_policy_analytic(30,t,p,cfg)['total_s']) for t in ts]
        r=race_candidates(30,cs,cfg,start_mobs=10,max_mobs=40,seed=123)
        self.assertIn(r.winner_index,range(3))
        self.assertTrue(r.survivor_indices)
        self.assertEqual(r.resolved,len(r.survivor_indices)==1)
        self.assertGreaterEqual(r.rounds,1)
        self.assertLessEqual(r.total_mobs_simulated,3*40)
        self.assertTrue(all(x.mobs in (10,20,40) for x in r.rows))

if __name__=='__main__': unittest.main()
