"""WF-BUDGET01: real Forever Game IR + production combat/recovery acceptance."""
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_budgeted_prefix import run_source_budgeted_prefix
from src.v2.generic_backend import _policy_combat_evaluation
from src.v2.source_policy_search import synthesize_source_policies


def test_l10_real_ordered_repeated_and_fallback():
    r = run_source_budgeted_prefix(class_key='druid', level=10, max_evaluations=32)
    assert r['attempted'] == 32
    assert r['evaluated'] > 0 and r['blocked'] > 0
    assert r['seed_skipped_by_budget'] == 0
    assert r['seed_count'] == 24
    assert r['winner']['actor_survived']
    assert r['winner']['recovery_s'] >= 0
    assert r['winner']['score_s_per_mob'] > 0
    ids = set(r['envelope']['actions'])
    for a in ids:
        assert any(tuple(x['prefix']) == (a,a) for x in r['trials']+r['failures'])
    # A→B and B→A really execute in that order, not APL priority.
    w, m = next(x for x in ids if x.startswith('wrath:')), next(x for x in ids if x.startswith('moonfire:'))
    for prefix in ((w,m),(m,w),(m,m)):
        t = next(x for x in r['trials'] if tuple(x['prefix']) == prefix)
        assert tuple(x['action_id'] for x in t['selected_actions'][:2]) == prefix
    # Adaptive extensions are selected from *measured* parent scores.
    extensions = [x for x in r['best_vs_budget'] if x['parent_score'] is not None]
    assert extensions and len({x['parent_score'] for x in extensions}) >= 2
    assert all(len(x['prefix']) >= 3 for x in extensions)
    assert r['unattempted_prefix_fallback_pairs'] > 0


def test_hard_budget_counts_failed_and_no_overrun():
    for budget in (1, 3, 12, 25):
        r = run_source_budgeted_prefix(class_key='druid', level=10, max_evaluations=budget)
        assert r['attempted'] <= budget
        assert r['attempted'] == r['evaluated'] + r['blocked']
        assert len(r['best_vs_budget']) == r['attempted']
        assert [x['attempt'] for x in r['best_vs_budget']] == list(range(1,r['attempted']+1))
        assert r['seed_skipped_by_budget'] == max(0,r['seed_count']-budget)


def test_l2_real_failure_is_resource_exhaustion_not_missing_spell():
    ir = build_game_ir_slice(class_key='druid', level=2)
    r = run_source_budgeted_prefix(class_key='druid', level=2, max_evaluations=8)
    assert len(r['envelope']['actions']) == 1
    assert r['attempted'] == 2  # single and repeated ordered pair
    assert r['status'] == 'BLOCKED_NO_KILLING_PREFIX'
    policy = synthesize_source_policies(ir, level=2)['policies'][0]
    score, execution, details = _policy_combat_evaluation(ir,level=2,policy_override=policy)
    assert score is None and not execution.timeline.target_defeated
    assert execution.timeline.as_dict()['resources_after']['mana'] == 7.0
    assert execution.timeline.as_dict()['target_end_health'] > 0


def test_illegal_prefix_fails_closed():
    ir = build_game_ir_slice(class_key='druid', level=10)
    policy = synthesize_source_policies(ir, level=10)['policies'][0]
    with pytest.raises(ValueError,match='BLOCKED_ILLEGAL_PREFIX'):
        _policy_combat_evaluation(ir,level=10,policy_override=policy,
                                  opening_action_ids=('not-in-sourced-IR',))


def test_mage_cross_class_production_runtime():
    r = run_source_budgeted_prefix(class_key='mage', level=20, max_evaluations=4)
    assert r['attempted'] == 4 and r['evaluated'] > 0
    assert r['winner']['score_s_per_mob'] > 0
    assert r['context_sha256'] != run_source_budgeted_prefix(
        class_key='druid',level=10,max_evaluations=1)['context_sha256']


def test_next_expensive_call_reacts_to_real_runtime_evidence():
    # Both cases use the same source actions, same scorer and same hard budget.
    # Incoming survival/recovery changes *real* measured scores, so the online
    # controller selects a different next expensive extension after the seeds.
    no_hits = run_source_budgeted_prefix(class_key='druid', level=10,
                                          max_evaluations=28, schedule_incoming_attacks=False)
    hits = run_source_budgeted_prefix(class_key='druid', level=10,
                                      max_evaluations=28, schedule_incoming_attacks=True)
    assert no_hits['seed_count'] == hits['seed_count'] == 24
    assert no_hits['context_sha256'] != hits['context_sha256']
    a = [tuple(x['prefix']) for x in no_hits['best_vs_budget'][24:]]
    b = [tuple(x['prefix']) for x in hits['best_vs_budget'][24:]]
    assert a != b
    assert all(x['parent_score'] is not None for x in hits['best_vs_budget'][24:])


def test_source_ir_mutation_invalidates_context_cache():
    from dataclasses import replace
    ir = build_game_ir_slice(class_key='druid', level=10)
    metadata = dict(ir.actor.metadata)
    metadata['source_build_revision'] = 'test-changed-provenance'
    changed = replace(ir, actor=replace(ir.actor, metadata=metadata))
    a = run_source_budgeted_prefix(class_key='druid', level=10,
                                   ir_slice=ir, max_evaluations=1)
    b = run_source_budgeted_prefix(class_key='druid', level=10,
                                   ir_slice=changed, max_evaluations=1)
    assert a['context_sha256'] != b['context_sha256']
