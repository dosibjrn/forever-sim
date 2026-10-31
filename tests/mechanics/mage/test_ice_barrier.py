from __future__ import annotations

from dataclasses import replace

from src import classic_mage_leveling_optimizer_v10 as eng
from src import policy_codec
from src.v2 import expected_engine as ee
from src.v2.local_search import proxy_score


def _barrier_prereq_30() -> eng.Talents:
    # Exactly 30 Frost points before the level-40 capstone.  Ice Block is the
    # real Classic prerequisite and is deliberately included in those 30.
    t=eng.Talents(
        imp_frostbolt=5, elemental_precision=3, ice_shards=5, frostbite=3,
        imp_frost_nova=2, permafrost=3, piercing_ice=3, arctic_reach=2,
        frost_channeling=3, ice_block=1,
    )
    assert eng.tree_points(t,'frost') == 30
    return t


def _pure_frost(*, barrier: bool) -> eng.Policy:
    return eng.Policy('FBo barrier' if barrier else 'FBo', 'frostbolt',
                      use_fireblast=False, use_nova=False, use_blink=False,
                      use_ice_barrier=barrier)


def test_ice_barrier_requires_ice_block_and_thirty_frost_points():
    ready=_barrier_prereq_30()
    assert eng.legal_add(ready,'ice_barrier')
    assert not eng.legal_add(replace(ready,ice_block=0,frost_warding=1),'ice_barrier')
    assert not eng.legal_add(replace(ready,frost_channeling=2),'ice_barrier')


def test_ice_barrier_classic_ranks_and_frost_channeling_cost():
    expected={40:(305.0,438.0),46:(360.0,549.0),52:(420.0,678.0),58:(480.0,818.0)}
    assert eng.ice_barrier_rank(39) is None
    for level,(mana,absorb) in expected.items():
        rank=eng.ice_barrier_rank(level)
        assert rank is not None
        assert rank.mana == mana
        assert rank.absorb == absorb
        assert eng.ice_barrier_mana_cost(level,eng.Talents()) == mana
        assert eng.ice_barrier_mana_cost(level,eng.Talents(frost_channeling=3)) == mana*.85


def test_barrier_absorb_prevents_pushback_only_while_hit_is_fully_absorbed():
    cfg=eng.SimConfig(generic_melee_hit_hp_frac=.1)
    mob=eng.Mob(41,1000.0)
    # A 100-damage hit is fully absorbed: no pushback event should be needed.
    s=eng.State(0.0,1000.0,1000.0,1000.0,0.0,ice_barrier_absorb=150.0,ice_barrier_until=60.0)
    assert eng._ice_barrier_absorbs_swing(s,mob,cfg)
    assert s.ice_barrier_absorb == 50.0
    # The next hit breaks with overflow; model conservatively allows pushback.
    assert not eng._ice_barrier_absorbs_swing(s,mob,cfg)
    assert s.ice_barrier_absorb == 0.0


def test_stochastic_barrier_policy_reduces_pushback_but_is_not_mandatory():
    talents=eng.add_point(_barrier_prereq_30(),'ice_barrier')
    cfg=eng.SimConfig(mob_swing=1.5,mob_swing_mix=(),use_best_water=True)
    off=eng.simulate_chain(40,talents,_pure_frost(barrier=False),cfg,n=20,seed=7)
    on=eng.simulate_chain(40,talents,_pure_frost(barrier=True),cfg,n=20,seed=7)
    assert on['casts_ice_barrier'] > 0
    assert on['pushback_s'] < off['pushback_s']
    # This exact workload intentionally demonstrates why talent != mandatory
    # cast: mana/GCD can outweigh saved pushback, so search must retain OFF.
    assert off['total_s'] < on['total_s']


def test_expected_engine_barrier_consumes_expected_swings_and_reduces_pushback():
    talents=eng.add_point(_barrier_prereq_30(),'ice_barrier')
    cfg=eng.SimConfig(mob_swing=1.5,mob_swing_mix=())
    stats=eng.player_stats(40,talents)
    mob=eng.Mob(41,eng.MOB_BASE_HP[41],cfg.mob_speed,1.5,cfg.melee_reach)
    rank=eng.latest(eng.FROSTBOLT,40)
    no=ee.ExpectedState(0,mob.hp,stats.max_mana,stats.max_mana,0,in_melee=True)
    shield=ee.ExpectedState(0,mob.hp,stats.max_mana,stats.max_mana,0,in_melee=True,
                            ice_barrier_absorb=eng.ice_barrier_rank(40).absorb,ice_barrier_until=60.0)
    a=ee._expected_pushback_s(3.0,no,mob,talents,rank,cfg)
    b=ee._expected_pushback_s(3.0,shield,mob,talents,rank,cfg)
    assert b < a
    assert shield.ice_barrier_absorb < eng.ice_barrier_rank(40).absorb


def test_policy_basis_contains_barrier_on_and_off_and_descriptor_roundtrips():
    talents=eng.add_point(_barrier_prereq_30(),'ice_barrier')
    frost=[p for p in ee.policy_candidates_expected(40,talents) if p.primary=='frostbolt']
    assert any(not p.use_ice_barrier for p in frost)
    assert any(p.use_ice_barrier for p in frost)
    on=next(p for p in frost if p.use_ice_barrier and not p.use_fireblast)
    desc=eng.policy_desc(on,40)
    assert 'IceBarrier' in desc
    restored=policy_codec.parse_descriptor(desc,40)
    assert restored.use_ice_barrier
    assert eng.policy_desc(restored,40) == desc


def test_structural_proxy_treats_barrier_as_option_not_forced_cost():
    ready=_barrier_prereq_30()
    talents=eng.add_point(ready,'ice_barrier')
    # Removing the point creates an under-spent comparator with otherwise exact
    # same mechanics. Optional Barrier must never make the structural estimate
    # worse than simply declining to press the spell.
    cfg=eng.SimConfig(use_best_water=True)
    assert proxy_score(40,talents,cfg,school='frost') <= proxy_score(40,ready,cfg,school='frost') + 1e-9


def test_smooth_level40_beam_preserves_ice_block_path_and_barrier_candidate():
    from src.v2.analytic_scorer import AnalyticOptions
    from src.v2.local_search import search_level_analytic
    cfg=eng.SimConfig(use_best_water=True)
    rows=search_level_analytic(40,cfg,options=AnalyticOptions(kill_boundary_model='normal2'),
                               beam_width=10,family_keep=2,final_k=12,school='frost')
    assert any(r.talents.ice_barrier == 1 and r.talents.ice_block == 1 for r in rows)


def test_mc_policy_basis_exposes_barrier_on_and_off_for_same_frost_rotation(monkeypatch):
    from src import pnp_cache
    talents=eng.add_point(_barrier_prereq_30(),'ice_barrier')
    monkeypatch.setenv('MAGE_PRIMARY_SCHOOL','frost')
    policies=pnp_cache._candidate_policies(40,talents,coarse=True)
    frost=[p for p in policies if eng.policy_primary_school(p)=='frost']
    assert any(p.use_ice_barrier for p in frost)
    assert any(not p.use_ice_barrier for p in frost)


def test_stochastic_barrier_absorb_and_duration_carry_to_next_pull():
    talents=eng.add_point(_barrier_prereq_30(),'ice_barrier')
    cfg=eng.SimConfig(mob_swing=2.5,mob_swing_mix=(),use_best_water=True,
                      generic_melee_hit_hp_frac=.03)
    policy=_pure_frost(barrier=True)
    first,state=eng.simulate_chain_incremental(40,talents,policy,cfg,target_n=1,seed=7)
    cds=state['cooldowns']
    assert len(cds) >= 10
    assert first['casts_ice_barrier'] == 1
    assert cds[7] > 0.0                 # Barrier still on cooldown.
    assert cds[8] > 0.0                 # Unspent absorb survives the pull/recovery.
    assert cds[9] > 0.0                 # Aura duration also survives.

    second,state2=eng.simulate_chain_incremental(40,talents,policy,cfg,target_n=2,seed=7,
                                                 continuation=state)
    # The second pull is protected by the carried shield; cooldown is not ready
    # at pull start, so no second Barrier cast is invented.
    assert second['casts_ice_barrier'] == 1
    assert state2['cooldowns'][8] < cds[8]
    assert state2['cooldowns'][9] < cds[9]


def test_expired_barrier_never_blocks_pushback_even_if_absorb_number_remains():
    cfg=eng.SimConfig(generic_melee_hit_hp_frac=.1)
    mob=eng.Mob(41,1000.0)
    s=eng.State(60.0,1000.0,1000.0,1000.0,0.0,
                ice_barrier_absorb=438.0,ice_barrier_until=60.0)
    assert not eng._ice_barrier_absorbs_swing(s,mob,cfg)
    assert s.ice_barrier_absorb == 0.0


def test_expected_barrier_carries_without_recasting_while_cooldown_is_down():
    talents=eng.add_point(_barrier_prereq_30(),'ice_barrier')
    cfg=eng.SimConfig(mob_swing=2.5,mob_swing_mix=(),use_best_water=True,
                      generic_melee_hit_hp_frac=.03)
    policy=_pure_frost(barrier=True)
    one=ee.simulate_fight_expected(40,talents,policy,cfg,mob_level=41,mob_swing=2.5)
    assert one.casts.get('ice_barrier',0.0) == 1.0
    assert one.end_cooldowns.ice_barrier > 0.0
    assert one.end_cooldowns.ice_barrier_absorb > 0.0
    assert one.end_cooldowns.ice_barrier_duration > 0.0

    two=ee.simulate_fight_expected(40,talents,policy,cfg,mob_level=42,mob_swing=2.5,
                                   cooldowns=one.end_cooldowns)
    assert two.casts.get('ice_barrier',0.0) == 0.0
    assert two.end_cooldowns.ice_barrier_absorb < one.end_cooldowns.ice_barrier_absorb
    assert two.end_cooldowns.ice_barrier_duration < one.end_cooldowns.ice_barrier_duration


def test_analytic_barrier_uses_stateful_pull_chain_not_independent_ready_masks():
    from src.v2.analytic_scorer import AnalyticOptions, score_policy_analytic
    talents=eng.add_point(_barrier_prereq_30(),'ice_barrier')
    cfg=eng.SimConfig(use_best_water=True)
    row=score_policy_analytic(40,talents,_pure_frost(barrier=True),cfg,
                              options=AnalyticOptions(kill_boundary_model='normal5q'))
    assert row['stateful_barrier_chain'] is True
    assert 0.0 < row['casts_ice_barrier'] < 90.0
    assert 0.0 <= row['cooldown_ready']['ice_barrier'] <= 1.0


def test_smooth_barrier_carry_tracks_mc_cast_frequency_and_same_on_off_decision():
    from src.v2.analytic_scorer import AnalyticOptions, score_policy_analytic
    talents=eng.add_point(_barrier_prereq_30(),'ice_barrier')
    cfg=eng.SimConfig(use_best_water=True,seed=123)
    opt=AnalyticOptions(kill_boundary_model='normal5q')
    off=_pure_frost(barrier=False); on=_pure_frost(barrier=True)
    mc_off=eng.simulate_chain(40,talents,off,cfg,n=100,seed=123)
    mc_on=eng.simulate_chain(40,talents,on,cfg,n=100,seed=123)
    sm_off=score_policy_analytic(40,talents,off,cfg,options=opt)
    sm_on=score_policy_analytic(40,talents,on,cfg,options=opt)
    assert mc_off['total_s'] < mc_on['total_s']
    assert sm_off['total_s'] < sm_on['total_s']
    assert abs(mc_on['casts_ice_barrier']-sm_on['casts_ice_barrier']) <= 5.0
    assert abs(sm_on['total_s']/mc_on['total_s']-1.0) < 0.03
