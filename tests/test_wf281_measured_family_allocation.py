"""WF281: cross-family search decisions use paid L2 outcomes, not raw L0 rankings."""
from dataclasses import replace
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_stateful_budgeted import run_source_stateful_budgeted
from src.v2.source_stateful_adapter import stateful_policy_as_prefix


def run(**kwargs):
    params = dict(class_key='druid', level=20, max_l2_attempts=48,
        max_event_transitions=6500, use_l1=False,
        search_guarded_continuations=True, search_mode_paths=True,
        family_budget_mode='measured_balanced')
    params.update(kwargs)
    return run_source_stateful_budgeted(**params)


def test_real_paid_families_find_better_l2_and_keep_exploration():
    r = run()
    assert r['status'] == 'BEST_KNOWN_BOUNDED'
    assert r['family_l2_counts']['initial'] >= 2
    assert all(n >= 2 for n in r['family_l2_counts'].values())
    assert r['family_verified_best']['cat_form:768'] < r['family_verified_best']['initial']
    assert r['winner']['score_s_per_mob'] < 26.0
    assert r['winner']['prefix'][0] == 'cat_form:768'
    assert r['winner']['prefix'][1] != r['winner']['prefix'][0]
    assert r['event_transitions'] <= 6500
    assert r['l2_attempts'] <= 48
    assert r['verification_complete']
    assert all(x['matches_scratch'] for x in r['scratch_verification'])
    assert r['family_decisions'][0]['family'] == 'initial'
    assert set(x['family'] for x in r['family_decisions']) == set(r['family_l2_counts'])


def test_hard_cap_and_no_free_success():
    r = run(max_l2_attempts=8, max_event_transitions=3)
    assert r['event_transitions'] <= 3
    assert r['l2_attempts'] <= 8
    assert r['winner'] is None
    assert r['status'] == 'BLOCKED_NO_L2_KILL'


def test_cross_class_no_mode_families():
    r = run_source_stateful_budgeted(class_key='rogue', level=20,
        max_l2_attempts=12, max_event_transitions=1300,
        search_mode_paths=True, family_budget_mode='measured_balanced',
        use_l1=False)
    assert set(r['family_l2_counts']) == {'initial'}
    assert r['family_l2_counts']['initial'] > 0
    assert r['event_transitions'] <= 1300


def test_source_mode_removed_is_not_a_forked_cached_candidate():
    ir = build_game_ir_slice(class_key='druid', level=20)
    altered = replace(ir, actions=tuple(a for a in ir.actions if a.id != 'cat_form:768'))
    r = run_source_stateful_budgeted(class_key='druid', level=20, ir_slice=altered,
        max_l2_attempts=16, max_event_transitions=3000,
        use_l1=False, search_mode_paths=True, use_prefix_cache=True,
        family_budget_mode='measured_balanced')
    assert 'cat_form:768' not in r['family_l2_counts']
    assert not any(x.get('tier')=='L2' and x['prefix'][0]=='cat_form:768'
                   for x in r['observations'] if x.get('prefix'))
    assert all(x['matches_scratch'] for x in r['scratch_verification'])


def test_adapter_preserves_family_evidence():
    ir = build_game_ir_slice(class_key='druid', level=20)
    r = stateful_policy_as_prefix(class_key='druid', level=20,
        ir_slice=ir, max_evaluations=24, max_event_transitions=4000,
        use_l1=False, search_mode_paths=True, family_budget_mode='measured_balanced')
    assert r['family_budget_mode'] == 'measured_balanced'
    assert len(r['family_l2_counts']) == 3
    assert sum(r['family_l2_counts'].values()) <= r['attempted']


def test_reject_unknown_scheduler():
    with pytest.raises(ValueError, match='family budget mode'):
        run_source_stateful_budgeted(class_key='druid', level=20,
            family_budget_mode='oracle_that_does_not_exist')


def test_changing_paid_l2_observation_changes_next_real_executor_call(monkeypatch):
    """Controlled negative: only synthetic *test* perturbation, not benchmark truth."""
    from src.v2 import source_stateful_budgeted as module
    original = module._policy_combat_evaluation
    def perturbed(*args, **kwargs):
        score, execution, details = original(*args, **kwargs)
        opening = kwargs.get('opening_action_ids', ())
        if score is not None and opening and opening[0] == 'cat_form:768':
            score = replace(score, score_s_per_100=score.score_s_per_100 + 10000.)
        return score, execution, details
    params=dict(max_l2_attempts=16,max_event_transitions=3000,
                search_guarded_continuations=False)
    ordinary = run(**params)
    monkeypatch.setattr(module,'_policy_combat_evaluation',perturbed)
    challenged = run(**params)
    first = [x['family'] for x in ordinary['family_decisions']]
    second = [x['family'] for x in challenged['family_decisions']]
    assert first[:6] == second[:6]  # paid pilot held constant
    assert first[6] == 'cat_form:768' and second[6] == 'initial'
    assert ordinary['family_l2_counts'] != challenged['family_l2_counts']
    assert ordinary['l2_attempts'] == challenged['l2_attempts'] == 16
    assert ordinary['event_transitions'] <= 3000 and challenged['event_transitions'] <= 3000


def test_coupled_gear_search_receives_family_budget():
    from src.v2.source_budgeted_gear import run_source_budgeted_gear
    r=run_source_budgeted_gear(class_key='druid',level=20,
        max_evaluations=75,initial_search=24,search_per_gear=16,
        max_gear_states=2,policy_search_backend='stateful',
        stateful_use_l1=False,stateful_search_guarded_continuations=True,
        stateful_search_mode_paths=True,
        stateful_family_budget_mode='measured_balanced',
        probe_stats=('agility','strength','stamina'),max_event_transitions=12000)
    assert r['status']=='EVALUATED_BOUNDED'
    assert r['attempted']<=75 and r['event_transitions']<=12000
    assert any(x['stage'].startswith('named_gear') for x in r['stages'])
    assert all(x.get('family_l2_counts') for x in r['stages'] if x.get('winner'))
    assert r['winner']['winner']['score_s_per_mob'] < 20
