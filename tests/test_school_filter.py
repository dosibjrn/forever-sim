from src import classic_mage_leveling_optimizer_v10 as eng
from src import pnp_cache


def test_policy_primary_school_ignores_utility_casts():
    p=eng.Policy('frost utility','frostbolt',use_fireblast=True,use_nova=True,use_blink=True)
    assert eng.policy_primary_school(p)=='frost'


def test_mc_policy_basis_respects_inherited_frost_filter(monkeypatch):
    monkeypatch.setenv(eng.PRIMARY_SCHOOL_ENV,'frost')
    t=eng.Talents(imp_frostbolt=5,elemental_precision=3,piercing_ice=3)
    for coarse in (True,False):
        ps=pnp_cache._candidate_policies(30,t,coarse)
        assert ps
        assert {eng.policy_primary_school(p) for p in ps} == {'frost'}


def test_direct_policy_optimizer_respects_frost_filter(monkeypatch):
    monkeypatch.setenv(eng.PRIMARY_SCHOOL_ENV,'frost')
    t=eng.Talents(imp_frostbolt=5,elemental_precision=3,piercing_ice=3)
    p,_=eng.optimize_policy(20,t,eng.SimConfig(),n=1,seed=7,coarse=True)
    assert eng.policy_primary_school(p)=='frost'
