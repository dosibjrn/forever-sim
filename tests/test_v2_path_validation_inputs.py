import pytest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2 import path_validation as pv
from src.v2.path_dp import LevelNode, PathResult, PathStep


def _node(level):
    t=eng.Talents()
    for _ in range(level-9):
        t=eng.add_point(t, 'imp_frostbolt')
    p=eng.Policy('FBo pure','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)
    return LevelNode(level,t,1.0,p,'test',{})


def _path(levels):
    steps=tuple(PathStep(_node(l),'start' if i==0 else 'point',None,0,float(i+1)) for i,l in enumerate(levels))
    return PathResult(steps,1.0,0,levels[-1] if levels else 0)


@pytest.mark.parametrize('value',[0,-1])
def test_estimate_rejects_nonpositive_mobs(value):
    with pytest.raises(ValueError, match='mobs_per_level must be > 0'):
        pv.estimate_path_stochastic(_path([11]),eng.SimConfig(),mobs_per_level=value,max_workers=1)


def test_estimate_rejects_empty_path():
    p=PathResult(tuple(),0.0,0,0)
    with pytest.raises(ValueError, match='at least one step'):
        pv.estimate_path_stochastic(p,eng.SimConfig(),max_workers=1)


def test_estimate_rejects_noncontiguous_path():
    with pytest.raises(ValueError, match='contiguous'):
        pv.estimate_path_stochastic(_path([11,13]),eng.SimConfig(),max_workers=1)


@pytest.mark.parametrize('kw,match',[
    ({'mobs_per_level_per_block':0},'mobs_per_level_per_block must be > 0'),
    ({'blocks':0},'blocks must be > 0'),
])
def test_paired_rejects_nonpositive_sampling(kw,match):
    p=_path([11])
    with pytest.raises(ValueError,match=match):
        pv.compare_paths_paired(p,p,eng.SimConfig(),max_workers=1,**kw)


def test_paired_rejects_different_ranges_before_simulation():
    with pytest.raises(ValueError,match='identical level ranges'):
        pv.compare_paths_paired(_path([11]),_path([11,12]),eng.SimConfig(),max_workers=1)

def test_estimate_serial_combines_level_weights(monkeypatch):
    def fake(level,talents,policy,cfg,n,seed):
        return {'mean_s_per_mob':float(level),'stderr_s_per_mob':0.5}
    monkeypatch.setattr(pv.eng,'simulate_chain',fake)
    monkeypatch.setattr(pv,'estimated_workload_mobs',lambda level:10.0)
    p=_path([11,12])
    got=pv.estimate_path_stochastic(p,eng.SimConfig(),mobs_per_level=7,seed=5,max_workers=1)
    assert [r.level for r in got.rows]==[11,12]
    assert got.total_seconds==230.0
    assert got.mobs_simulated==14
    assert got.stderr_seconds == pytest.approx((25+25)**0.5)


def test_estimate_rejects_step_without_policy():
    n=_node(11)
    n=LevelNode(n.level,n.talents,n.score_s_per_100,None,n.source,n.details)
    p=PathResult((PathStep(n,'start',None,0,1.0),),1.0,0,11)
    with pytest.raises(ValueError,match='has no frozen policy'):
        pv.estimate_path_stochastic(p,eng.SimConfig(),mobs_per_level=1,max_workers=1)


def test_paired_serial_uses_common_seed_and_reports_delta(monkeypatch):
    seen=[]
    def fake(level,talents,policy,cfg,n,seed):
        seen.append((level,seed))
        # distinguish paths through the talent count while preserving paired seed
        return {'mean_s_per_mob':float(talents.points()),'stderr_s_per_mob':0.0}
    monkeypatch.setattr(pv.eng,'simulate_chain',fake)
    monkeypatch.setattr(pv,'estimated_workload_mobs',lambda level:2.0)
    a=_path([11])
    # Different legal-ish node with one extra point is enough for the paired math test.
    nb=_node(11)
    tb=eng.add_point(nb.talents,'elemental_precision')
    nb=LevelNode(11,tb,nb.score_s_per_100,nb.policy,nb.source,nb.details)
    b=PathResult((PathStep(nb,'start',None,0,1.0),),1.0,0,11)
    got=pv.compare_paths_paired(a,b,eng.SimConfig(),mobs_per_level_per_block=3,blocks=2,seed=7,max_workers=1)
    assert got.mean_delta_seconds==-2.0
    assert got.stderr_delta_seconds==0.0
    assert got.block_deltas_seconds==(-2.0,-2.0)
    assert seen[0][1]==seen[1][1]
    assert seen[2][1]==seen[3][1]
