from src import game_context
from src.engine_registry import reset_engine_cache


def test_runner_cumulative_path_overrides_historical_frontier_route():
    try:
        game_context.configure('forever','mage'); reset_engine_cache()
        from src.engine_registry import eng
        from src.v2.path_dp import LevelNode, PathStep, PathResult
        from src.v2.mature_decision_artifacts import _overlay_canonical_paths
        t=eng.Talents(imp_frostbolt=5, elemental_precision=3, ice_shards=5, permafrost=3,
                      frostbite=3, piercing_ice=3, frost_channeling=3, ice_lance=1,
                      arctic_reach=2, shatter=3)
        p=eng.Policy('IL','frostbolt',use_proc_ice_lance=True,use_nova=True,nova_rank1=True,nova_move_yards=5)
        n=LevelNode(40,t,360000.0/170.5,p,'event_structural',{})
        path=PathResult((PathStep(n,'start',None,0,1000.0),),1000.0,0,40)
        routes={'targets':{'40':{'routes':{'unconstrained':{'status':'available','path':{'allocation':'old','mobs_per_hour':153.0}}}}}}
        regrets={'targets':{'40':{'routes':{'unconstrained':{'status':'available','objective_seconds':1200.0}}}}}
        routes,regrets=_overlay_canonical_paths(routes,regrets,{40:path},eng,eng.SimConfig())
        out=routes['targets']['40']['routes']['unconstrained']['path']
        assert out['talent_ranks']['ice_lance']==1
        assert out['mobs_per_hour'] > 170.0
        assert 'Frozen/FoF' in out['policy']
        assert regrets['targets']['40']['routes']['unconstrained']['objective_seconds']==1000.0
    finally:
        game_context.configure('classic','mage'); reset_engine_cache()
