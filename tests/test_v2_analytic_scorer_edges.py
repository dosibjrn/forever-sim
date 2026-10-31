from types import SimpleNamespace
import math
import pytest

from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2 import analytic_scorer as a


@pytest.fixture
def cfg():
    return eng.SimConfig(use_best_water=True, root_break_mode='scaled')


def frost_policy(**kw):
    base=dict(use_fireblast=False,use_nova=False,use_blink=False)
    base.update(kw)
    return eng.Policy('edge frost','frostbolt',**base)


def test_workload_scenarios_reject_bad_shape_and_weights(cfg):
    t=eng.Talents(); p=frost_policy()
    with pytest.raises(ValueError, match='equal length'):
        a._workload_scenarios(30,t,p,cfg,a.AnalyticOptions(mob_offsets=(1,),workload_weights=(.5,.5)))
    for weights in ((),(-1.0,2.0),(math.nan,1.0),(math.inf,1.0)):
        offsets=tuple(range(1,len(weights)+1))
        with pytest.raises(ValueError, match='finite and nonnegative|sum positive'):
            a._workload_scenarios(30,t,p,cfg,a.AnalyticOptions(mob_offsets=offsets,workload_weights=weights))
    with pytest.raises(ValueError, match='sum positive'):
        a._workload_scenarios(30,t,p,cfg,a.AnalyticOptions(workload_weights=(0.0,0.0)))


def test_unknown_boundary_and_cooldown_models_fail_fast(cfg):
    t=eng.Talents(); p=frost_policy()
    with pytest.raises(ValueError, match='unknown kill_boundary_model'):
        a.score_policy_analytic(30,t,p,cfg,options=a.AnalyticOptions(kill_boundary_model='wat'))
    with pytest.raises(ValueError, match='unknown cooldown_model'):
        a.score_policy_analytic(30,t,p,cfg,options=a.AnalyticOptions(cooldown_model='wat'))


def test_normal2_boundary_is_deterministic_and_normalized(cfg):
    t=eng.Talents(imp_frostbolt=5,ice_shards=5)
    p=frost_policy()
    o=a.AnalyticOptions(kill_boundary_model='normal2')
    rows=a._workload_scenarios(30,t,p,cfg,o)
    assert len(rows) in (2,4)
    assert sum(w for _off,_hp,w in rows) == pytest.approx(1.0)
    assert all(hp>0 and w>=0 for _off,hp,w in rows)
    r1=a.score_policy_analytic(30,t,p,cfg,options=o)
    r2=a.score_policy_analytic(30,t,p,cfg,options=o)
    assert r1['total_s'] == r2['total_s']
    assert r1['kill_boundary_model']=='normal2'


def test_joint_cooldown_model_exercises_full_ready_table(cfg):
    t=eng.Talents(imp_frostbolt=5,imp_frost_nova=2)
    p=frost_policy(use_fireblast=True,use_nova=True,use_blink=True)
    o=a.AnalyticOptions(cooldown_model='joint',cooldown_max_iter=5)
    r=a.score_policy_analytic(30,t,p,cfg,options=o)
    # Three active cooldowns => 2^3 masks x two workload classes per FP iteration.
    assert set(r['cooldown_ready'])=={'fire_blast','nova','blink'}
    assert all(0.0<=v<=1.0 for v in r['cooldown_ready'].values())
    assert r['state_evaluations'] == 8*2*r['combustion_fixed_point_iters']


def test_combustion_state_evaluations_match_actual_kernel_calls(cfg,monkeypatch):
    p=eng.Policy('fire','fireball',use_fireblast=False,use_nova=False,use_blink=False)
    t=eng.Talents(imp_fireball=5,critical_mass=3,fire_power=5,combustion=1)
    original=a.simulate_fight_expected
    calls=[]
    def counted(*args,**kwargs):
        calls.append((kwargs.get('mob_level'),kwargs.get('combustion_extra_crit')))
        return original(*args,**kwargs)
    monkeypatch.setattr(a,'simulate_fight_expected',counted)
    r=a.score_policy_analytic(40,t,p,cfg)
    assert r['state_evaluations']==len(calls)
    assert len(calls)>2*r['combustion_fixed_point_iters']  # final converged-table rebuild is included


def test_combustion_on_nonfire_policy_has_zero_bonus(cfg):
    t=eng.Talents(combustion=1)
    r=a.score_policy_analytic(40,t,frost_policy(),cfg)
    assert r['combustion_extra_crit']==0.0


def test_policy_family_and_exhaustive_empty_guard(cfg):
    mixed=eng.Policy('mixed','frostbolt',fireball_block=2,scorch_block=3,use_fireblast=False,use_nova=False,use_blink=False)
    other=eng.Policy('other','wand',use_fireblast=False,use_nova=False,use_blink=False)
    assert a._policy_family(mixed)=='fire'
    assert a._policy_family(other)=='other'
    with pytest.raises(ValueError,match='no analytical policies'):
        a.optimize_policy_analytic_exhaustive(30,eng.Talents(),cfg,policies=[])


def test_normal5q_kill_boundary_quadrature_has_center_and_normalized_weights():
    from src.v2.analytic_scorer import AnalyticOptions, _workload_scenarios
    t=eng.Talents(imp_frostbolt=5, elemental_precision=3, ice_shards=5)
    p=eng.Policy('FBo','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
    rows=_workload_scenarios(45,t,p,eng.SimConfig(),AnalyticOptions(
        mob_offsets=(1,), workload_weights=(1.0,), kill_boundary_model='normal5q'))
    assert len(rows)==5
    assert abs(sum(w for _off,_hp,w in rows)-1.0)<1e-12
    assert any(abs(hp-1.0)<1e-12 and abs(w-0.2)<1e-12 for _off,hp,w in rows)
    assert all(abs(w-0.2)<1e-12 for _off,_hp,w in rows)
    lows=[hp for _off,hp,_w in rows if hp<1.0]
    highs=[hp for _off,hp,_w in rows if hp>1.0]
    assert len(lows)==len(highs)==2
