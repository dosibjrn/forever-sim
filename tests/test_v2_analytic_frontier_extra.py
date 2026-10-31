import pytest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2 import analytic_frontier as af
from src.v2.path_dp import LevelNode


def _policy():
    return eng.Policy('FBo pure','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)


def _node(level,t,score,source='smooth'):
    return LevelNode(level,t,score,_policy(),source,{})


def test_default_views_are_separate_hard_and_smooth_models():
    views=af.default_views()
    assert [v.name for v in views]==['hard','smooth']
    assert views[0].options.kill_boundary_model=='hard'
    assert views[1].options.kill_boundary_model=='normal5q'


def test_score_build_view_tags_analytic_view(monkeypatch):
    pol=_policy()
    monkeypatch.setattr(af,'optimize_policy_analytic',lambda level,t,cfg,options:(pol,{'total_s':123.0,'x':1}))
    view=af.AnalyticView('smooth',af.AnalyticOptions())
    n=af.score_build_view(11,eng.Talents(),eng.SimConfig(),view)
    assert n.score_s_per_100==123.0
    assert n.source=='smooth'
    assert n.details['analytic_view']=='smooth'


def test_score_builds_skips_expected_scoring_failures(monkeypatch):
    good=eng.Talents()
    bad=eng.Talents(imp_frostbolt=1)
    def fake(level,t,cfg,view):
        if t==bad: raise ValueError('bad')
        return _node(level,t,10.0)
    monkeypatch.setattr(af,'score_build_view',fake)
    rows=af.score_builds_view(11,[bad,good],eng.SimConfig(),af.default_views()[1])
    assert len(rows)==1 and rows[0].talents==good


def test_union_view_leaders_deduplicates_same_key_within_source():
    t=eng.Talents(imp_frostbolt=1)
    rows=[_node(10,t,10.0,'smooth'),_node(10,t,11.0,'smooth')]
    got=af.union_view_leaders([rows],top_k_per_view=8,family_keep=1)
    assert len(got)==1


def test_union_view_leaders_keeps_same_build_from_distinct_views():
    t=eng.Talents(imp_frostbolt=1)
    got=af.union_view_leaders([[_node(10,t,10.0,'hard')],[_node(10,t,9.0,'smooth')]])
    assert {n.source for n in got}=={'hard','smooth'}
