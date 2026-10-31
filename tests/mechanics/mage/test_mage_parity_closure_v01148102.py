from src.rulesets.forever.classes.mage import engine as e
from src.v2.mage_class_model import MageClassModel


def test_mage_capability_matrix_is_symmetric_and_bounded():
    f=e.MODEL_FIDELITY
    assert e.VERIFIED_LEVEL_CAP == 30
    assert e.PLANNING_LEVEL_CAP == 40
    assert f['verified_level_cap']==30 and f['planning_level_cap']==40
    assert set(f['capability_matrix']) == {'frost','arcane','fire','shared'}
    for school in ('frost','arcane','fire'):
        assert f['capability_matrix'][school]['talent_legality_l10_l40']=='source_backed'
        assert 'single_target_rotation' in f['capability_matrix'][school]
    assert f['capability_matrix']['shared']['gear']=='canonical_sqlite_runtime_selection'
    assert f['strategy_capabilities']['mage.blizzard_aoe_leveling'] is False


def test_node_school_uses_policy_primary_school_not_talent_tree():
    m=MageClassModel(e)
    class N: pass
    n=N(); n.policy=e.Policy('x','fireball',use_fireblast=False,use_nova=False,use_blink=False)
    assert m._node_school(n)=='fire'
    n.policy=e.Policy('x','arcane_missiles',use_fireblast=False,use_nova=False,use_blink=False)
    assert m._node_school(n)=='arcane'
    n.policy=e.Policy('x','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
    assert m._node_school(n)=='frost'


def test_event_rerank_calls_all_three_school_leaders(monkeypatch):
    from types import SimpleNamespace
    from dataclasses import dataclass
    @dataclass(frozen=True)
    class T:
        ice_lance:int=0
    @dataclass
    class N:
        key:str
        score_s_per_100:float
        talents:T
        policy:object
        details:dict
        source:str='x'
    class E:
        RULESET='forever'
        def policy_primary_school(self,p): return p.school
        def policy_search(self, level, talents, cfg, school, n, seed):
            calls.append(school)
            return {'best_found':{'mobs_per_hour':100+len(calls),'kill_seconds_per_mob':10,'recovery_seconds_per_mob':2,'travel_seconds_per_mob':1,'rotation':school}}
    calls=[]
    m=MageClassModel(E())
    rows=[N('f',100,T(),SimpleNamespace(school='frost'),{}),N('a',110,T(),SimpleNamespace(school='arcane'),{}),N('r',120,T(),SimpleNamespace(school='fire'),{})]
    out=m.rerank_repaired_pools({20:rows},object())
    assert set(calls)=={'frost','arcane','fire'}
    assert {x.details['event_structural_rerank']['school'] for x in out[20]}=={'frost','arcane','fire'}


def test_bounded_l20_l40_representative_school_sanity():
    """I14 milestone sanity without six full route optimizations.

    Each Mage school must expose a legal structural candidate at L20 and L40
    and the shared expected-state scorer must produce a finite leveling score.
    """
    import math
    from src import game_context
    from src.v2 import expected_engine
    from tools.report_backend_reconciliation import _mage_structural_build

    game_context.configure('forever', 'mage')
    cfg=e.SimConfig(seed=7,use_best_water=True)
    for level in (20,40):
        for school in ('frost','arcane','fire'):
            talents=_mage_structural_build(level,school)
            policies=e.candidate_policies_for_build(level,talents,focused=True,school=school)
            assert policies, (level,school)
            assert all(e.policy_primary_school(p)==school for p in policies)
            rows=[expected_engine.score_policy(level,talents,p,cfg,cycle_pulls=2) for p in policies[:5]]
            assert rows
            assert all(math.isfinite(float(r['total_s'])) and float(r['total_s'])>0 for r in rows)
