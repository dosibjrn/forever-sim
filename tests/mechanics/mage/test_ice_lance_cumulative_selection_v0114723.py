from src import game_context
from src.engine_registry import reset_engine_cache


def _forever_mage():
    game_context.configure('forever','mage'); reset_engine_cache()


def _classic_mage():
    game_context.configure('classic','mage'); reset_engine_cache()


def test_l30_production_all_spec_pool_contains_event_winning_ice_lance_lane():
    try:
        _forever_mage()
        from src.engine_registry import eng
        from src.v2.runner import _search_worker
        from src.v2.class_model import active_class_model
        from src.v2.analytic_scorer import AnalyticOptions
        cfg=eng.SimConfig()
        level,rows=_search_worker((30,cfg,AnalyticOptions(kill_boundary_model='normal5q',kill_boundary_sigma_scale=1.0),24,4,24,'all'))
        corrected=active_class_model().rerank_repaired_pools({level:rows},cfg)[level]
        winner=min(corrected,key=lambda n:(float(n.score_s_per_100),n.key))
        assert int(getattr(winner.talents,'ice_lance',0) or 0)==1
        assert int(getattr(winner.talents,'imp_fireball',0) or 0)==0
        assert float(winner.score_s_per_100) < 360000.0/130.0
    finally:
        _classic_mage()
