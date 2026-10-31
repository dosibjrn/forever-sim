import pytest

from src import game_context
from src.engine_registry import reset_engine_cache, get_engine
from src.v2.analytic_scorer import AnalyticOptions
from src.v2.local_search import search_level_analytic


def test_forever_mage_l11_generic_kernel_preserves_mature_candidate_scores():
    game_context.configure('forever','mage'); reset_engine_cache()
    mage=get_engine(); cfg=mage.SimConfig(); options=AnalyticOptions()
    legacy=search_level_analytic(11,cfg,options=options,beam_width=10,family_keep=2,final_k=8,school='all')
    from src.v2.runner import _search_worker
    level,generic=_search_worker((11,cfg,options,10,2,8,'all',False,0))
    assert level == 11
    assert [n.key for n in generic] == [n.key for n in legacy]
    assert [n.score_s_per_100 for n in generic] == pytest.approx([n.score_s_per_100 for n in legacy], rel=0, abs=1e-9)
