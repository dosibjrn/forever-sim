from __future__ import annotations
import unittest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.expected_engine import (optimize_policy_expected, policy_candidates_expected,
    policy_candidates_expected_exhaustive, compact_fire_cadence_policies)

class PolicySearchTests(unittest.TestCase):
    def test_compact_policy_space(self):
        t=eng.Talents(imp_fireball=5,elemental_precision=3,ignite=5,flame_throwing=2,pyroblast=1)
        ps=policy_candidates_expected(40,t)
        self.assertLess(len(ps),100)
        self.assertGreater(len(ps),10)


    def test_kiss_fire_basis_is_small_and_reference_is_superset(self):
        for imp in range(4):
            t=eng.Talents(imp_fireball=5,ignite=5,imp_scorch=imp)
            compact=policy_candidates_expected(40,t)
            full=policy_candidates_expected_exhaustive(40,t)
            self.assertLessEqual(len(compact),16)
            self.assertGreater(len(full),50)
            ck={tuple(getattr(p,f) for f in p.__dataclass_fields__ if f!='name') for p in compact}
            fk={tuple(getattr(p,f) for f in p.__dataclass_fields__ if f!='name') for p in full}
            self.assertTrue(ck.issubset(fk))

    def test_imp_scorch_conditions_projectile_aware_templates(self):
        t0=eng.Talents(imp_scorch=0)
        t3=eng.Talents(imp_scorch=3)
        p0=compact_fire_cadence_policies(40,t0)
        p3=compact_fire_cadence_policies(40,t3)
        self.assertNotEqual(
            {(p.fireball_block,p.scorch_block,p.fire_cycle_phase) for p in p0},
            {(p.fireball_block,p.scorch_block,p.fire_cycle_phase) for p in p3})
        # Explicitly retain projectile-first archetypes such as
        # FBa,FBa,Sc,Sc,Sc and FBa,FBa,FBa,Sc,Sc,Sc.
        for ps in (p0,p3):
            sigs={(p.fireball_block,p.scorch_block,p.fire_cycle_phase) for p in ps}
            self.assertIn((2,3,0),sigs)
            self.assertIn((3,3,0),sigs)

    def test_predict_refine_returns_deterministic_winner(self):
        t=eng.Talents(imp_frostbolt=5,elemental_precision=3,ice_shards=5,permafrost=3,piercing_ice=3)
        cfg=eng.SimConfig(use_best_water=True)
        p1,r1=optimize_policy_expected(40,t,cfg)
        p2,r2=optimize_policy_expected(40,t,cfg)
        self.assertEqual(eng.policy_desc(p1,40),eng.policy_desc(p2,40))
        self.assertEqual(r1['total_s'],r2['total_s'])
        self.assertEqual(r1['proposal_pulls'],2)
        self.assertEqual(r1['refine_pulls'],6)

if __name__=='__main__': unittest.main()
