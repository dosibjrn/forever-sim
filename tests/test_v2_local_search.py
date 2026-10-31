from __future__ import annotations
import unittest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.local_search import search_level, family, _spell_proxy

class LocalSearchTests(unittest.TestCase):
    def test_independent_level_search_returns_legal_full_allocations(self):
        cfg=eng.SimConfig(use_best_water=True)
        rows=search_level(20,cfg,beam_width=16,family_keep=3,final_k=8,proposal_pulls=1,refine_pulls=2)
        self.assertTrue(rows)
        self.assertTrue(all(x.talents.points()==11 for x in rows))
        self.assertEqual(rows,sorted(rows,key=lambda x:x.score_s_per_100))
        self.assertIn('frost',{family(x.talents) for x in rows})
        self.assertIn('fire',{family(x.talents) for x in rows})

    def test_structural_proxy_values_range_slow_and_pushback_talents(self):
        from dataclasses import replace
        cfg=eng.SimConfig(use_best_water=True)

        frost=eng.Talents(imp_frostbolt=5,elemental_precision=3,piercing_ice=3)
        base=_spell_proxy(40,41,frost,cfg,'frostbolt')
        self.assertLess(_spell_proxy(40,41,replace(frost,permafrost=3),cfg,'frostbolt'),base)
        self.assertLess(_spell_proxy(40,41,replace(frost,arctic_reach=2),cfg,'frostbolt'),base)

        fire=eng.Talents(imp_fireball=5,elemental_precision=3,fire_power=5)
        fbase=_spell_proxy(40,41,fire,cfg,'fireball')
        self.assertLess(_spell_proxy(40,41,replace(fire,burning_soul=2),cfg,'fireball'),fbase)
        self.assertLess(_spell_proxy(40,41,replace(fire,flame_throwing=2),cfg,'fireball'),fbase)

if __name__=='__main__': unittest.main()


def test_smooth_arcane_lane_prefers_subtlety_over_synthetic_filler_on_exact_tie():
    from src.v2.local_search import search_level_analytic
    from src.v2.analytic_scorer import AnalyticOptions
    cfg=eng.SimConfig(use_best_water=True)
    rows=search_level_analytic(20,cfg,options=AnalyticOptions(kill_boundary_model='normal2'),
                               beam_width=10,family_keep=2,final_k=8)
    arcane=next(x for x in rows if family(x.talents)=='arcane')
    # Baseline mobs have no penetrable inherent resistance, so this is a true
    # score tie.  The real utility talent must dominate synthetic gate filler.
    assert arcane.talents.arcane_subtlety == 2
    assert arcane.talents.arcane_filler <= 3

def test_frost_only_analytic_search_returns_only_frost_primary_policies_and_keeps_arcane_support_legal():
    from src.v2.local_search import search_level_analytic
    from src.v2.analytic_scorer import AnalyticOptions
    cfg=eng.SimConfig(use_best_water=True)
    rows=search_level_analytic(20,cfg,options=AnalyticOptions(kill_boundary_model='normal2'),
                               beam_width=10,family_keep=2,final_k=8,school='frost')
    assert rows
    assert all(eng.policy_primary_school(x.policy)=='frost' for x in rows)
    # Frost-only constrains the rotation, not the talent tree. Arcane support
    # candidates (including real Subtlety) must remain representable.
    assert any(eng.tree_points(x.talents,'arcane')>0 for x in rows)
    assert any(x.talents.arcane_subtlety>0 for x in rows)
