from __future__ import annotations

import unittest

from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2.expected_engine import CooldownState, ExpectedState, expected_direct_components, score_policy, simulate_fight_expected


class ExpectedEngineTests(unittest.TestCase):
    def setUp(self):
        self.cfg=eng.SimConfig(use_best_water=True)

    def test_reproducible_without_seed(self):
        t=eng.Talents(imp_frostbolt=5, elemental_precision=3)
        p=eng.Policy('pure','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
        a=score_policy(30,t,p,self.cfg)
        b=score_policy(30,t,p,self.cfg)
        self.assertEqual(a['total_s'],b['total_s'])
        self.assertEqual(a['cooldown_end'],b['cooldown_end'])

    def test_damage_range_is_mean(self):
        t=eng.Talents()
        stats=eng.player_stats(30,t)
        rank=eng.latest(eng.FIREBALL,30)
        s=ExpectedState(0,1000,stats.max_mana,stats.max_mana,35)
        got=expected_direct_components(30,31,rank,t,stats,self.cfg,s)
        base=(rank.dmin+rank.dmax)/2
        hit=eng.spell_hit(30,31,'fire',t)
        resist=eng.resistance_damage_multiplier(30,t,self.cfg,'fire',31)
        crit=stats.spell_crit
        want=base*hit*resist*(1+crit*.5)
        self.assertAlmostEqual(got['damage'],want,places=8)

    def test_cooldown_state_is_explicit_transition(self):
        t=eng.Talents(imp_fireball=5,imp_fire_blast=3)
        p=eng.Policy('fire','fireball',use_fireblast=True,use_nova=False,use_blink=False,fireblast_execute_frac=.95)
        out=simulate_fight_expected(30,t,p,self.cfg,cooldowns=CooldownState())
        self.assertGreater(out.total_s,0)
        self.assertIsInstance(out.end_cooldowns,CooldownState)

    def test_fireblast_down_changes_or_equals_result(self):
        t=eng.Talents(imp_fireball=5,imp_fire_blast=3)
        p=eng.Policy('fire','fireball',use_fireblast=True,use_nova=False,use_blink=False,fireblast_execute_frac=.95)
        up=simulate_fight_expected(30,t,p,self.cfg,cooldowns=CooldownState(fire_blast=0))
        down=simulate_fight_expected(30,t,p,self.cfg,cooldowns=CooldownState(fire_blast=999))
        self.assertLessEqual(up.total_s,down.total_s+1e-9)


if __name__=='__main__': unittest.main()


def test_smooth_resistance_expectation_matches_mc_model_for_arcane_subtlety():
    """The analytic expectation must stay mechanically identical to MC resistance."""
    from src.v2.expected_engine import _expected_resist_multiplier
    cfg=eng.SimConfig(mob_magic_resistance=17.0, mob_fire_resistance=23.0,
                      mob_frost_resistance=11.0, mob_arcane_resistance=29.0)
    for level,mob_level in ((20,20),(30,31),(45,47)):
        for ranks in (0,1,2):
            t=eng.Talents(arcane_subtlety=ranks)
            for table in (eng.FROSTBOLT,eng.FIREBALL,eng.SCORCH,eng.ARCANE_MISSILES):
                r=eng.latest(table,level)
                if r is None:
                    continue
                got=_expected_resist_multiplier(level,mob_level,r,t,cfg)
                binary=r.spell in getattr(eng,'_BINARY_DAMAGE_SPELLS',())
                pct=eng.effective_magic_resistance_percent(level,mob_level,r.school,t,cfg,binary=binary)
                if binary:
                    want=1.0-pct
                else:
                    chances=eng._partial_resist_chances(pct)
                    want=1.0-sum((0.25*i)*(c/10000.0) for i,c in enumerate(chances))
                assert abs(got-want)<1e-12


def test_arcane_subtlety_helps_all_spell_schools_when_target_has_reducible_resistance():
    from src.v2.expected_engine import ExpectedState, expected_direct_components
    cfg=eng.SimConfig(mob_magic_resistance=10.0)
    level=30; mob_level=31
    base=eng.Talents()
    sub=eng.Talents(arcane_subtlety=2)
    for table in (eng.FROSTBOLT,eng.FIREBALL,eng.SCORCH,eng.ARCANE_MISSILES):
        r=eng.latest(table,level)
        if r.spell=='arcane_missiles':
            # AM has a dedicated expected channel path; multiplier itself still proves all-school penetration.
            from src.v2.expected_engine import _expected_resist_multiplier
            assert _expected_resist_multiplier(level,mob_level,r,sub,cfg) > _expected_resist_multiplier(level,mob_level,r,base,cfg)
            continue
        stats=eng.player_stats(level,base)
        state=ExpectedState(0.0,1e9,stats.max_mana,stats.max_mana,30.0)
        a=expected_direct_components(level,mob_level,r,base,stats,cfg,state)
        b=expected_direct_components(level,mob_level,r,sub,stats,cfg,state)
        assert b['damage'] > a['damage']


def test_arcane_subtlety_does_not_fake_penetrate_level_difference_resistance():
    from src.v2.expected_engine import _expected_resist_multiplier
    cfg=eng.SimConfig()  # no inherent resistance
    r=eng.latest(eng.FIREBALL,30)
    zero=_expected_resist_multiplier(30,32,r,eng.Talents(),cfg)
    sub=_expected_resist_multiplier(30,32,r,eng.Talents(arcane_subtlety=2),cfg)
    assert sub == zero
