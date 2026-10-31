"""WF259 real combat+recovery feedback into on-demand named gear selection."""
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_budgeted_gear import run_source_budgeted_gear


def _run_druid(budget=120):
    return run_source_budgeted_gear(class_key='druid',level=10,
        max_evaluations=budget,initial_search=24,search_per_gear=24)


def test_real_gear_stat_feedback_and_fresh_policy_on_each_named_state():
    r=_run_druid()
    assert r['status']=='EVALUATED_BOUNDED'
    assert r['attempted']==120 == r['evaluated']+r['blocked']
    assert len(r['best_vs_budget'])==120
    assert [x['attempt'] for x in r['best_vs_budget']]==list(range(1,121))
    assert r['named_gear_states_evaluated']>=3
    naked,first,second=r['stages'][:3]
    assert naked['winner']['score_s_per_mob']>first['winner']['score_s_per_mob']
    assert second['winner']['score_s_per_mob']<first['winner']['score_s_per_mob']
    assert all(s['search_is_fresh_from_source_singles_pairs'] for s in r['stages'])
    assert all(s['context_sha256']!=naked['context_sha256'] for s in r['stages'][1:])
    assert len({s['context_sha256'] for s in r['stages']})==len(r['stages'])
    assert first['gear']['slots']['weapon']['source_url'].startswith('https://')
    assert first['gear']['slots']['weapon']['item_id']>0
    assert first['seed_skipped']==0 and second['seed_skipped']==0
    assert len(r['sensitivity_history'])>=2
    assert r['sensitivity_history'][0]['values'] != r['sensitivity_history'][1]['values']
    assert r['winner']['winner']['score_s_per_mob']<naked['winner']['score_s_per_mob']
    assert [x['best_s_per_mob'] for x in r['best_vs_budget'] if x['best_s_per_mob'] is not None]==sorted(
        [x['best_s_per_mob'] for x in r['best_vs_budget'] if x['best_s_per_mob'] is not None],reverse=True)


def test_partial_final_named_gear_search_is_explicit_not_silent():
    r=_run_druid(120)
    assert r['stages'][-1]['incomplete_seed_coverage']
    assert r['stages'][-1]['seed_skipped']>0
    assert r['complete_search'] is False


def test_mage_l20_real_gear_policy_switch_and_cross_class():
    r=run_source_budgeted_gear(class_key='mage',level=20,
        max_evaluations=140,initial_search=40,search_per_gear=40,
        max_gear_states=3)
    assert r['attempted']==140
    naked=r['stages'][0]['winner']
    first=r['stages'][1]['winner']
    assert naked['prefix']!=first['prefix']
    assert first['score_s_per_mob']<naked['score_s_per_mob']
    assert all(s['winner']['selected_actions'] for s in r['stages'] if s['winner'])
    assert r['stages'][1]['gear']['slots']['weapon']['item_id']>0


def test_budget_negative_input_and_illegal_source_fail_closed():
    with pytest.raises(ValueError,match='positive'):
        _run_druid(0)
    with pytest.raises(ValueError,match='duplicate'):
        run_source_budgeted_gear(class_key='druid',level=10,max_evaluations=4,
                                 probe_stats=('spirit','spirit'))
    with pytest.raises(ValueError,match='mismatch'):
        run_source_budgeted_gear(class_key='mage',level=10,max_evaluations=4,
                                 ir_slice=build_game_ir_slice(class_key='druid',level=10))


def test_tiny_budget_has_no_unpaid_stat_probe_or_named_gear_runtime():
    r=_run_druid(3)
    assert r['attempted'] == 3
    assert len(r['stages'])==1
    assert len(r['best_vs_budget'])==3


def test_source_revision_changes_state_cache_key():
    ir=build_game_ir_slice(class_key='druid',level=10)
    changed=replace(ir,actor=replace(ir.actor,metadata={**ir.actor.metadata,
                                              'source_build_revision':'wf259_probe'}))
    a=run_source_budgeted_gear(class_key='druid',level=10,max_evaluations=1,ir_slice=ir)
    b=run_source_budgeted_gear(class_key='druid',level=10,max_evaluations=1,ir_slice=changed)
    assert a['source_context_sha256'] != b['source_context_sha256']
