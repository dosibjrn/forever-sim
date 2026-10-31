from types import SimpleNamespace
import sys
import pytest
from src import classic_mage_leveling_optimizer_v10 as eng
from src.v2 import runner
from src.v2.path_dp import LevelNode,PathStep,PathResult


def _policy():
    return eng.Policy('FBo pure','frostbolt',use_fireblast=False,use_nova=False,use_blink=False)


def _talents(level):
    t=eng.Talents()
    # Enough for the tiny test levels only.
    for _ in range(level-9):
        for name in ('imp_frostbolt','elemental_precision'):
            if eng.legal_add(t,name):
                t=eng.add_point(t,name); break
    return t


def _node(level,score=None):
    return LevelNode(level,_talents(level),float(score or level),_policy(),'smooth',{})


def _args(**kw):
    base=dict(start_level=11,end_level=12,beam_width=3,family_keep=1,final_k=2,parent_k=1,
              workers=1,max_respecs=2,buy_water=True,view='smooth')
    base.update(kw); return SimpleNamespace(**base)


def _path_from_pools(pools,respecs=0):
    steps=[]; total=0.0
    for i,l in enumerate(sorted(pools)):
        n=pools[l][0]; total+=n.score_s_per_100
        steps.append(PathStep(n,'start' if i==0 else 'point',None,respecs,total))
    return PathResult(tuple(steps),total,respecs,max(pools))


def test_base_snapshot_records_effective_config():
    s=runner._base_snapshot(_args(buy_water=False,view='both'))
    assert s['running'] is True
    assert s['config']['water_mode']=='conjured_water'
    assert s['config']['views']=='both'


def test_publish_view_merges_existing_view(monkeypatch):
    seen=[]; monkeypatch.setattr(runner,'publish',lambda s: seen.append(dict(s)))
    snap={'views':{'smooth':{'a':1}}}
    runner._publish_view(snap,'smooth',b=2)
    assert snap['views']['smooth']=={'a':1,'b':2}
    assert len(seen)==1


def test_search_worker_returns_level_and_rows(monkeypatch):
    monkeypatch.setattr(runner,'search_level_analytic',lambda level,cfg,**kw:[_node(level)])
    view=runner.default_views()[1]
    level,rows=runner._search_worker((11,eng.SimConfig(),view.options,3,1,2))
    assert level==11 and rows[0].level==11


def test_run_view_serial_full_orchestration(monkeypatch):
    snap={'views':{}}; args=_args(); view=runner.default_views()[1]
    monkeypatch.setattr(runner,'search_level_analytic',lambda level,cfg,**kw:[_node(level)])
    monkeypatch.setattr(runner.mc_bridge,'publish_level_candidates',lambda *a,**k:None)
    monkeypatch.setattr(runner,'publish',lambda s:None)
    monkeypatch.setattr(runner,'close_pools_backward',lambda pools,cfg,view,**kw:pools)
    monkeypatch.setattr(runner,'solve_path_dp',lambda pools,max_respecs,**kw:_path_from_pools(pools,max_respecs))
    monkeypatch.setattr(runner.mc_bridge,'publish_paths',lambda *a,**k:3)
    repaired,paths=runner._run_view(snap,view,eng.SimConfig(),args)
    assert sorted(repaired)==[11,12]
    assert set(paths)=={'0','1','2','per_level_best'}
    assert snap['views']['smooth']['status']=='complete'
    assert snap['views']['smooth']['school']=='all'
    assert snap['views']['smooth']['mc_bridge_paths']==3
    assert snap['views']['smooth']['best_path']['hours'] is not None



def test_run_view_persists_frost_school_in_completed_view(monkeypatch):
    snap={'views':{}}; args=_args(start_level=11,end_level=11,max_respecs=0,school='frost'); view=runner.default_views()[1]
    monkeypatch.setattr(runner,'search_level_analytic',lambda level,cfg,**kw:[_node(level)])
    monkeypatch.setattr(runner.mc_bridge,'publish_level_candidates',lambda *a,**k:None)
    monkeypatch.setattr(runner,'publish',lambda s:None)
    monkeypatch.setattr(runner,'close_pools_backward',lambda pools,cfg,view,**kw:pools)
    monkeypatch.setattr(runner,'solve_path_dp',lambda pools,max_respecs,**kw:_path_from_pools(pools,max_respecs))
    monkeypatch.setattr(runner.mc_bridge,'publish_paths',lambda *a,**k:0)
    runner._run_view(snap,view,eng.SimConfig(),args)
    assert snap['views']['smooth']['school']=='frost'


def test_run_view_keeps_dp_error_per_budget(monkeypatch):
    snap={'views':{}}; args=_args(max_respecs=1); view=runner.default_views()[1]
    monkeypatch.setattr(runner,'search_level_analytic',lambda level,cfg,**kw:[_node(level)])
    monkeypatch.setattr(runner.mc_bridge,'publish_level_candidates',lambda *a,**k:None)
    monkeypatch.setattr(runner,'publish',lambda s:None)
    monkeypatch.setattr(runner,'close_pools_backward',lambda pools,cfg,view,**kw:pools)
    def solve(pools,max_respecs,**kw):
        if max_respecs==1: raise RuntimeError('no path')
        return _path_from_pools(pools,0)
    monkeypatch.setattr(runner,'solve_path_dp',solve)
    monkeypatch.setattr(runner.mc_bridge,'publish_paths',lambda *a,**k:1)
    _,paths=runner._run_view(snap,view,eng.SimConfig(),args)
    assert paths['1']['error']=='RuntimeError: no path'
    assert snap['views']['smooth']['best_path']['hours'] is not None


def test_main_success_publishes_complete(monkeypatch):
    published=[]
    monkeypatch.setattr(sys,'argv',['runner','--start-level','11','--end-level','11','--workers','1'])
    monkeypatch.setattr(runner.mc_bridge,'reset',lambda **kw:None)
    monkeypatch.setattr(runner,'publish',lambda s:published.append(dict(s)))
    def fake_run(snap,view,cfg,args):
        snap.setdefault('views',{})[view.name]={'best_path':{'hours':1.25}}
        return {},{}
    monkeypatch.setattr(runner,'_run_view',fake_run)
    runner.main()
    assert published[-1]['running'] is False
    assert published[-1]['phase']=='complete'
    assert published[-1]['best_analytic']['view']=='smooth'


def test_main_error_publishes_error_then_raises(monkeypatch):
    published=[]
    monkeypatch.setattr(sys,'argv',['runner','--start-level','11','--end-level','11','--workers','1'])
    monkeypatch.setattr(runner.mc_bridge,'reset',lambda **kw:None)
    monkeypatch.setattr(runner,'publish',lambda s:published.append(dict(s)))
    monkeypatch.setattr(runner,'_run_view',lambda *a,**k:(_ for _ in ()).throw(RuntimeError('boom')))
    with pytest.raises(RuntimeError,match='boom'):
        runner.main()
    assert published[-1]['phase']=='error'
    assert 'RuntimeError: boom' in published[-1]['message']


def test_progress_publish_due_throttles_full_snapshot_rewrites():
    assert runner._progress_publish_due(1,49)
    assert runner._progress_publish_due(5,49)
    assert runner._progress_publish_due(49,49)
    assert not runner._progress_publish_due(2,49)
    assert not runner._progress_publish_due(48,49)


def test_serial_search_publishes_progress_in_batches(monkeypatch):
    snap={'views':{}}; args=_args(start_level=11,end_level=22,max_respecs=0); view=runner.default_views()[1]
    monkeypatch.setattr(runner,'search_level_analytic',lambda level,cfg,**kw:[_node(level)])
    monkeypatch.setattr(runner.mc_bridge,'publish_level_candidates',lambda *a,**k:None)
    published=[]
    monkeypatch.setattr(runner,'publish',lambda s: published.append((s['views']['smooth'].get('status'),s['views']['smooth'].get('levels_done'))))
    monkeypatch.setattr(runner,'close_pools_backward',lambda pools,cfg,view,**kw:pools)
    monkeypatch.setattr(runner,'solve_path_dp',lambda pools,max_respecs,**kw:_path_from_pools(pools,max_respecs))
    monkeypatch.setattr(runner.mc_bridge,'publish_paths',lambda *a,**k:0)
    runner._run_view(snap,view,eng.SimConfig(),args)
    searching_done=[d for status,d in published if status=='searching' and d is not None]
    assert searching_done==[0,1,5,10,12]


def test_main_frost_shortcut_sets_effective_school(monkeypatch):
    published=[]
    monkeypatch.setattr(sys,'argv',['runner','--start-level','11','--end-level','11','--workers','1','--frost'])
    monkeypatch.setattr(runner.mc_bridge,'reset',lambda **kw:None)
    monkeypatch.setattr(runner,'publish',lambda s:published.append(dict(s)))
    seen={}
    def fake_run(snap,view,cfg,args):
        seen['school']=args.school
        snap.setdefault('views',{})[view.name]={'best_path':{'hours':1.25}}
        return {},{}
    monkeypatch.setattr(runner,'_run_view',fake_run)
    runner.main()
    assert seen['school']=='frost'
    assert published[0]['config']['school']=='frost'


def test_main_frost_shortcut_rejects_conflicting_school(monkeypatch):
    monkeypatch.setattr(sys,'argv',['runner','--frost','--school','fire'])
    with pytest.raises(SystemExit) as exc:
        runner.main()
    assert exc.value.code == 2
