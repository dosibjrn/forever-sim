from src import game_context
from src.engine_registry import reset_engine_cache


def _forever_mage():
    game_context.configure('forever','mage')
    reset_engine_cache()
    from src.rulesets.forever.classes.mage import engine, real_gear
    return engine, real_gear


def test_mage_weighted_selector_stays_on_canonical_sql_items():
    _engine, gear = _forever_mage()
    rows=gear.equipped_items(20, {'intellect':1.0,'spell_power':5.0,'spirit':0.0})
    assert rows
    assert all(x.item_id is not None for x in rows)
    assert all(x.model_kind == 'canonical_sqlite_item' for x in rows)


def test_mage_final_candidate_runs_bounded_gear_stat_fixed_point():
    engine, _gear = _forever_mage()
    from src.v2.local_search import _mage_fixed_point_score
    from src.v2.analytic_scorer import AnalyticOptions
    t=engine.Talents(imp_frostbolt=5, elemental_precision=3)
    p,row=_mage_fixed_point_score(20,t,engine.SimConfig(),options=AnalyticOptions(),school='frost')
    fp=row['gear_fixed_point']
    assert fp['class']=='mage'
    assert 1 <= fp['iterations'] <= 4
    assert fp['trace']
    # A bounded non-converged walk must publish the best state it actually
    # scored, never the arbitrary final proposal (the L20 oscillation bug).
    assert float(row['total_s']) <= min(float(x['score_s_per_100']) for x in fp['trace']) + 1e-9
    assert row['stat_weights']['stats']['intellect']['seconds_saved_per_100_per_point'] is not None
    slots=(row['gear_stats'] or {}).get('slots') or {}
    assert slots and all(x.get('model_kind')=='canonical_sqlite_item' for x in slots.values())
