from src import game_context
from src.engine_registry import reset_engine_cache


def _forever_mage():
    game_context.configure('forever','mage'); reset_engine_cache()


def _classic_mage():
    game_context.configure('classic','mage'); reset_engine_cache()


def test_l20_all_spec_search_retains_ice_lance_corridor():
    try:
        _forever_mage()
        from src.engine_registry import eng
        from src.v2.local_search import search_level_analytic
        rows=search_level_analytic(20,eng.SimConfig(),beam_width=24,family_keep=4,final_k=24,school='all')
        il=[r for r in rows if int(getattr(r.talents,'ice_lance',0) or 0)>0]
        assert len(il) >= 1
    finally:
        _classic_mage()


def test_l20_all_spec_per_level_best_can_select_ice_lance():
    try:
        _forever_mage()
        from src.engine_registry import eng
        from src.v2.local_search import search_level_analytic
        from src.v2.runner import _per_level_best_path
        cfg=eng.SimConfig()
        rows=search_level_analytic(20,cfg,beam_width=24,family_keep=4,final_k=24,school='all')
        path=_per_level_best_path({20:rows},cfg,start_level=20,end_level=20,respec_seconds=1.0)
        step=path['steps'][0]
        assert step.get('selection_validation',{}).get('winner_has_ice_lance') is True
        assert 'ice_lance=1' in str(step.get('allocation') or '')
        assert 'IL' in str(step.get('rotation') or '')
        assert 'HP→Wand≤2' in str(step.get('rotation') or '')
    finally:
        _classic_mage()
