"""Checkpoint-scoped action L0 coverage, source uncertainty and live search use."""
from __future__ import annotations
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_action_proxy import checkpoint_action_proxy_coverage,score_ir_action
from src.v2.source_budgeted_prefix import source_prefix_envelope
from tools.wf317_first_checkpoint_source_plan import make_plan


def test_all_ir_actions_have_positive_proxy_and_no_unknown_zero():
    ir=build_game_ir_slice(class_key='druid',level=20)
    c=checkpoint_action_proxy_coverage(ir,level=20)
    assert c['ir_proxy_scored_count']==c['ir_action_count']>0
    assert c['source_index_proxy_scored_count']==c['source_index_in_level_window']==124
    assert c['no_unknown_silently_zeroed']
    assert not c['complete_legal_spell_coverage_proven']
    assert all(x['search_priority']>0 for x in c['ir_actions'])
    assert all(x['l0_proxy_priority']>0 for x in c['indexed_ranks'])


def test_unknown_indexed_rank_kept_with_uncertainty_not_executable():
    ir=build_game_ir_slice(class_key='druid',level=20)
    c=checkpoint_action_proxy_coverage(ir,level=20)
    unmatched=[x for x in c['indexed_ranks'] if not x['matched_action_ids']]
    assert len(unmatched)==c['source_index_only_uncertain_count']>0
    assert all(x['proxy_status']=='INDEX_ONLY_UNCERTAIN_L0' for x in unmatched)
    assert all('not_compiled_to_IR' in x['source_uncertainty'] for x in unmatched)
    assert all(x['legal_at_checkpoint_proven'] is False for x in unmatched)
    assert c['trainer_hint_proxy_scored']==c['trainer_hint_ranks']


def test_proxy_covers_modes_healing_and_upkeep_not_just_offense():
    ir=build_game_ir_slice(class_key='druid',level=20)
    rows=checkpoint_action_proxy_coverage(ir,level=20)['ir_actions']
    roles={role for row in rows for role in row['roles']}
    assert {'mode_change','healing','combat_enabler','resource','direct_damage'} <= roles
    assert any('mode_value_depends_on_destination_actions_and_shifting_cost' in r['uncertainty'] for r in rows)


def test_optimizer_uses_proxy_priority_without_dropping_actions():
    ir=build_game_ir_slice(class_key='druid',level=20)
    env=source_prefix_envelope(ir,level=20,include_auto_fallback=True)
    scores={r['action_id']:r['search_priority'] for r in env['l0_action_proxy_coverage']['ir_actions']}
    for ids in (env['actions'],env['fillers']):
        actual=[scores.get(a,0.) for a in ids]
        assert actual==sorted(actual,reverse=True)
    assert any(x['mode_id']=='cat' for x in env['mode_paths'])
    assert any(x['mode_id']=='bear' for x in env['mode_paths'])


def test_capture_frontier_prioritizes_source_proxy_and_keeps_all_ranks():
    plan=make_plan(class_key='druid',level=20)
    assert plan['l0_proxy_priority_used_for_capture_order']
    assert plan['l0_source_index_proxy_scored']==124
    assert plan['counts']['planned_source_ids']==119
    assert sum(len(c['spell_ids']) for c in plan['capture_plan']['chunks'])==119


def test_primary_wowhead_provenance_is_bound_to_its_index_id():
    from src.game.data.forever.source_indexed_action_coverage import _source_spell_ids
    ir=build_game_ir_slice(class_key='druid',level=20)
    enrage=next(a for a in ir.actions if a.id=='enrage:5229')
    assert 5229 in _source_spell_ids(enrage)
    c=checkpoint_action_proxy_coverage(ir,level=20)
    row=next(x for x in c['indexed_ranks'] if x['spell_id']==5229)
    assert row['matched_action_ids']==['enrage:5229']
