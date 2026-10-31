import inspect

from src import game_context
from src.engine_registry import get_engine, reset_engine_cache
from src.v2.class_model import active_class_model
from src.v2.forever_class_models import (
    DruidClassModel,
    HunterClassModel,
    PaladinClassModel,
)
from src.v2.mage_class_model import MageClassModel


def _model(class_name):
    game_context.configure('forever', class_name)
    reset_engine_cache()
    return active_class_model(), get_engine()


def test_forever_classes_have_explicit_models_and_strategy_is_plugin_owned():
    expected = {
        'mage': (MageClassModel, 'analytic_views'),
        'hunter': (HunterClassModel, 'continuity_beam'),
        'druid': (DruidClassModel, 'continuity_beam'),
        'paladin': (PaladinClassModel, 'continuity_beam'),
    }
    for name, (kind, strategy) in expected.items():
        model, _ = _model(name)
        assert isinstance(model, kind)
        assert model.runner_strategy() == strategy


def test_bundled_forever_adapters_preserve_existing_engine_evaluator_contract():
    for name, kind in (
        ('hunter', HunterClassModel),
        ('druid', DruidClassModel),
        ('paladin', PaladinClassModel),
    ):
        model, eng = _model(name)
        assert isinstance(model, kind)
        base = eng.Talents()
        from src.v2.class_model import SearchContext
        ev = model.evaluate(SearchContext(level=10, build=base, metadata={'profile': 'all'}))
        raw = eng.experimental_level_score(10, base, 'all')
        assert ev.score_s_per_100 == float(raw['total_s'])
        assert model.candidate_optimization_is_bundled() is True


def test_runner_has_no_forever_class_name_or_engine_kind_dispatch_and_mage_hooks_live_in_model():
    import src.v2.runner as runner
    main_src = inspect.getsource(runner.main)
    worker_src = inspect.getsource(runner._search_worker)
    full_src = inspect.getsource(runner)
    assert 'ENGINE_KIND' not in main_src
    assert "CLASS_NAME',None)=='mage" not in full_src.replace(' ', '')
    assert 'ice_lance' not in full_src
    assert 'policy_search' not in full_src
    assert 'runner_strategy()' in worker_src


def test_route_publication_is_shared_pipeline_for_both_search_strategies():
    import src.v2.experimental_classes as continuity
    import src.v2.mature_decision_artifacts as analytic
    continuity_src = inspect.getsource(continuity.run)
    analytic_src = inspect.getsource(analytic.publish_mature_class_decisions)
    assert 'decision_pipeline import publish_decisions' in continuity_src
    assert 'decision_pipeline import publish_decisions' in analytic_src
    assert 'solve_routes(' not in continuity_src
    assert 'solve_routes(' not in analytic_src
