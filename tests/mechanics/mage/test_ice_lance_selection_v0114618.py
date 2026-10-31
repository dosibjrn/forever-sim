from src import game_context
from src.engine_registry import reset_engine_cache


def _forever_mage():
    game_context.configure('forever','mage')
    reset_engine_cache()


def _classic_mage():
    game_context.configure('classic','mage')
    reset_engine_cache()


def test_l20_search_retains_multiple_ice_lance_corridors():
    try:
        _forever_mage()
        from src.engine_registry import eng
        from src.v2.local_search import search_level_analytic
        rows=search_level_analytic(20,eng.SimConfig(),beam_width=24,family_keep=4,final_k=24,school='frost')
        il=[r for r in rows if int(getattr(r.talents,'ice_lance',0) or 0)>0]
        assert len(il) >= 3
        assert any(int(getattr(r.talents,'frostbite',0) or 0) >= 3 for r in il)
    finally:
        _classic_mage()


def test_l20_event_validation_reports_ice_lance_mph_vs_optimum():
    try:
        _forever_mage()
        from src.v2.mage_structural_validation import validate_ice_lance
        result=validate_ice_lance(20,n=16,seed=7)
        assert result['optimum']['mobs_per_hour'] > 0
        assert result['best_ice_lance']['mobs_per_hour'] > 0
        assert result['best_ice_lance']['ice_lance'] is True
        # Current L20 retained pool should select the Ice-Lance build under the
        # same event comparison, not merely prove that the spell can execute.
        assert result['ice_lance_is_optimum'] is True
        assert abs(result['delta_mobs_per_hour']) < 1e-9
    finally:
        _classic_mage()


def test_decisions_listener_exposes_ice_lance_validation_control():
    from src import listener
    assert 'Validate Ice Lance vs optimum' in listener.DECISIONS_HTML
    assert '/api/decisions/validate' in listener.DECISIONS_HTML
