from __future__ import annotations
import unittest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.analytic_scorer import score_policy_analytic

class AnalyticScorerTests(unittest.TestCase):
    def setUp(self): self.cfg=eng.SimConfig(use_best_water=True,root_break_mode='scaled')
    def test_reproducible_and_bounded_state_count(self):
        t=eng.Talents(imp_frostbolt=5,elemental_precision=3)
        p=eng.Policy('u','frostbolt',use_fireblast=True,use_nova=True,use_blink=True)
        a=score_policy_analytic(30,t,p,self.cfg); b=score_policy_analytic(30,t,p,self.cfg)
        self.assertEqual(a['total_s'],b['total_s'])
        self.assertLessEqual(a['state_evaluations'],16)
        self.assertTrue(all(0<=x<=1 for x in a['cooldown_ready'].values()))
    def test_clearcasting_is_expected_mana_not_policy_branch(self):
        p=eng.Policy('pure','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
        a=score_policy_analytic(30,eng.Talents(),p,self.cfg)
        b=score_policy_analytic(30,eng.Talents(arcane_concentration=5),p,self.cfg)
        self.assertLess(b['total_s'],a['total_s'])
    def test_combustion_has_nonnegative_expected_bonus(self):
        p=eng.Policy('fire','fireball',use_fireblast=False,use_nova=False,use_blink=False)
        t=eng.Talents(imp_fireball=5,critical_mass=3,fire_power=5,combustion=1)
        r=score_policy_analytic(40,t,p,self.cfg)
        self.assertGreaterEqual(r['combustion_extra_crit'],0)

if __name__=='__main__': unittest.main()
