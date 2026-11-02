from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_action_coverage import audit_source_action_coverage
from src.v2.source_policy_search import synthesize_source_policies


def test_druid_cat_finisher_is_searchable_but_semantics_still_block_completion():
    ir = build_game_ir_slice(class_key='druid', level=20)
    envelope = synthesize_source_policies(ir, level=20, mode_id='cat',
                                          include_auto_resource_fallback=True, max_policies=1024)
    audit = audit_source_action_coverage(ir, level=20, search_envelopes=(envelope,))
    rip = next(x for x in audit['actions'] if x['action_id'] == 'rip:20')
    assert rip['legal_mode_ids'] == ['cat']
    assert rip['blocking'] and rip['in_search']
    assert 'ResourceScaledPeriodicEffect' in rip['effect_types']
    assert rip['semantic_gaps']
    assert audit['status'] == 'INCOMPLETE'
    assert not audit['complete_optimizer']


def test_coverage_is_not_auto_completed_by_excluding_unknown_actions():
    ir = build_game_ir_slice(class_key='druid', level=20)
    empty = audit_source_action_coverage(ir, level=20)
    assert empty['blocker_count'] > 0
    assert empty['audited_action_count'] > 0
    assert not empty['complete_optimizer']


def test_level_locks_are_not_reported_as_available():
    ir = build_game_ir_slice(class_key='druid', level=10)
    audit = audit_source_action_coverage(ir, level=10)
    assert all(row['action_id'] != 'rip:20' for row in audit['actions'])
