from __future__ import annotations
import unittest

from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.stochastic_diagnostics import (
    Candidate, stochastic_estimate, long_reference, se_calibration,
    selection_diagnostics, make_one_point_pairs, pair_delta_diagnostics,
)
from src.v2.analytic_scorer import score_policy_analytic


class StochasticDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.cfg=eng.SimConfig(use_best_water=True,root_break_mode='scaled')
        self.p=eng.Policy('pure','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
        self.a=eng.Talents(imp_frostbolt=5,elemental_precision=3)
        self.b=eng.Talents(imp_frostbolt=5,elemental_precision=2,ice_shards=1)

    def cand(self,t):
        return Candidate(t,self.p,score_policy_analytic(30,t,self.p,self.cfg)['total_s'])

    def test_estimate_exposes_existing_v1_stderr(self):
        e=stochastic_estimate(30,self.a,self.p,self.cfg,mobs=20,seed=7)
        self.assertEqual(e.mobs,20)
        self.assertGreater(e.mean_s_per_mob,0)
        self.assertGreaterEqual(e.stderr_s_per_mob,0)

    def test_long_reference_combines_blocks(self):
        t=long_reference(30,self.cand(self.a),self.cfg,mobs_per_block=20,blocks=2,seed=9)
        self.assertEqual(t.mobs_total,40)
        self.assertGreater(t.s_per_100,0)
        self.assertGreaterEqual(t.se_s_per_100,0)

    def test_small_selection_diagnostic_runs(self):
        cs=[self.cand(self.a),self.cand(self.b)]
        r=selection_diagnostics(30,cs,self.cfg,search_mobs=10,search_reps=2,
                                truth_mobs_per_block=20,truth_blocks=2,top_k=1,seed=11)
        self.assertEqual(r['candidate_count'],2)
        self.assertIn('mean_winner_optimism_s_per_100',r)
        self.assertIn('analytic_truth_spearman',r)

    def test_pair_generator_and_diagnostic(self):
        pairs=make_one_point_pairs(30,pairs_per_tree=1,seed=13)
        self.assertTrue(pairs)
        r=pair_delta_diagnostics(30,pairs[:1],self.cfg,block_mobs=10,blocks=2,
                                 truth_mobs_per_block=20,truth_blocks=1,seed=17)
        self.assertEqual(r['pairs'],1)
        self.assertIn('median_paired_over_independent_delta_sd',r)

if __name__=='__main__': unittest.main()
