from __future__ import annotations

from dataclasses import replace

from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2 import expected_engine as ee
from src.v2.analytic_scorer import AnalyticOptions, score_policy_analytic


def _pure_frost() -> eng.Policy:
    return eng.Policy('FBo','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)


def _frostbite_base() -> eng.Talents:
    return eng.Talents(
        imp_frostbolt=5,
        elemental_precision=3,
        ice_shards=5,
        imp_frost_nova=2,
        frostbite=3,
        piercing_ice=3,
    )


def test_expected_frostbolt_projectile_pipelines_into_next_cast_and_enables_shatter():
    level=45
    talents=replace(_frostbite_base(),shatter=5)
    cfg=eng.SimConfig()
    stats=eng.player_stats(level,talents,cfg.owl_intensity)
    mob=eng.Mob(level+1,1e9,cfg.mob_speed,cfg.mob_swing,cfg.melee_reach)
    rank=eng.latest(eng.FROSTBOLT,level)
    state=ee.ExpectedState(0.0,mob.hp,stats.max_mana,stats.max_mana,eng.effective_range(rank,talents))
    casts={}

    assert ee._cast_direct(state,rank,level,talents,stats,cfg,mob,casts)
    assert len(state.projectiles)==1
    first_impact=state.projectiles[0].impact
    assert state.t < first_impact
    assert not state.engaged

    # While cast #2 is in progress, bolt #1 lands and can proc expected
    # Frostbite.  Crit is snapshotted only when cast #2 completes, so Shatter
    # must see that root probability just like the stochastic event ordering.
    assert ee._cast_direct(state,rank,level,talents,stats,cfg,mob,casts)
    assert state.t > first_impact
    assert state.engaged
    assert state.root_probability > 0.0
    assert len(state.projectiles)==1
    second=state.projectiles[0]
    assert second.comp['crit_p'] > stats.spell_crit


def test_smooth_shatter_values_frostbite_for_single_target_frostbolt():
    level=45
    cfg=eng.SimConfig()
    p=_pure_frost()
    base=_frostbite_base()
    opt=AnalyticOptions(kill_boundary_model='normal5q')
    no=score_policy_analytic(level,replace(base,shatter=0),p,cfg,options=opt)['total_s']
    yes=score_policy_analytic(level,replace(base,shatter=5),p,cfg,options=opt)['total_s']
    assert yes < no


def test_shatter_does_not_create_free_value_without_a_root_source():
    level=45
    cfg=eng.SimConfig(root_break_mode='never')
    p=_pure_frost()
    base=replace(_frostbite_base(),frostbite=0)
    opt=AnalyticOptions(kill_boundary_model='normal5q')
    no=score_policy_analytic(level,replace(base,shatter=0),p,cfg,options=opt)['total_s']
    yes=score_policy_analytic(level,replace(base,shatter=5),p,cfg,options=opt)['total_s']
    assert abs(yes-no) < 1e-9



def test_inflight_kill_does_not_spend_mana_for_unfinished_next_cast():
    level=45
    talents=_frostbite_base()
    cfg=eng.SimConfig()
    stats=eng.player_stats(level,talents,cfg.owl_intensity)
    rank=eng.latest(eng.FROSTBOLT,level)
    # One expected bolt is enough to kill.  The first projectile lands while
    # cast #2 is in progress; v1 aborts that unfinished cast without spending it.
    probe=ee.ExpectedState(0.0,1e9,stats.max_mana,stats.max_mana,eng.effective_range(rank,talents))
    comp=ee.expected_direct_components(level,level+1,rank,talents,stats,cfg,probe)
    mob=eng.Mob(level+1,comp['damage']*.5,cfg.mob_speed,cfg.mob_swing,cfg.melee_reach)
    state=ee.ExpectedState(0.0,mob.hp,stats.max_mana,stats.max_mana,eng.effective_range(rank,talents))
    casts={}
    assert ee._cast_direct(state,rank,level,talents,stats,cfg,mob,casts)
    first_spend_t=state.last_mana_spend
    mana_after_first=state.mana
    assert casts['frostbolt']==1.0
    assert ee._cast_direct(state,rank,level,talents,stats,cfg,mob,casts)
    assert state.hp <= ee.EPS
    assert casts['frostbolt']==1.0
    assert state.last_mana_spend==first_spend_t
    assert state.mana >= mana_after_first  # only in-cast regen, no second spend


def test_projectile_travel_does_not_tick_cooldowns_twice():
    level=45
    talents=_frostbite_base()
    cfg=eng.SimConfig()
    stats=eng.player_stats(level,talents,cfg.owl_intensity)
    rank=eng.latest(eng.FROSTBOLT,level)
    mob=eng.Mob(level+1,1e9,cfg.mob_speed,cfg.mob_swing,cfg.melee_reach)
    state=ee.ExpectedState(0.0,mob.hp,stats.max_mana,stats.max_mana,eng.effective_range(rank,talents),
                           cooldowns=ee.CooldownState(nova=20.0))
    casts={}
    t0=state.t
    assert ee._cast_direct(state,rank,level,talents,stats,cfg,mob,casts)
    elapsed=state.t-t0
    assert elapsed < (max(5.0,state.distance)/rank.missile_speed + rank.cast)
    assert abs(state.cooldowns.nova-(20.0-elapsed)) < 1e-9


def test_smooth_winters_chill_is_not_lost_to_cast_count_thresholds():
    level=35
    cfg=eng.SimConfig()
    p=_pure_frost()
    base=eng.Talents(imp_frostbolt=5,elemental_precision=3,ice_shards=5,piercing_ice=3)
    opt=AnalyticOptions(kill_boundary_model='normal5q')
    no=score_policy_analytic(level,base,p,cfg,options=opt)['total_s']
    yes=score_policy_analytic(level,replace(base,winters_chill=5),p,cfg,options=opt)['total_s']
    assert yes < no
