"""WF-GEN02c2c: resource generating actions discovered without class strategy branching."""
from dataclasses import replace

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import ResourceChangeEffect
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.source_mode_search import evaluate_discovered_mode_search


def test_source_generation_and_resource_threshold_in_bear_mode():
    ir = build_game_ir_slice(class_key='druid', level=20)
    envelope = synthesize_source_policies(ir, level=20, mode_id='bear',
        include_auto_resource_fallback=True)
    assert 'enrage:5229' in envelope['eligible_buttons']
    guarded = [r for policy in envelope['policies'] for r in policy.rules
        if r.action_id == 'enrage:5229' and r.conditions]
    assert guarded
    assert any(c.kind == 'resource_threshold' and c.resource_id == 'rage'
        and c.value == 50.0 for r in guarded for c in r.conditions)


def test_generic_mode_runtime_executes_sourced_resource_generation():
    result = evaluate_discovered_mode_search(class_key='druid', level=20)
    assert result['candidate_count'] == result['evaluated_count'] + result['rejected_count']
    assert any(any(a['action_id'] == 'enrage:5229' for a in row['selected_actions'])
        for row in [result['winner'], *result['alternatives']])
    assert result['optimization_ready'] is False


def test_same_resource_rule_works_on_renamed_source_ir():
    ir = build_game_ir_slice(class_key='druid', level=20)
    ir = replace(ir, id='synthetic:renamed', policies=())
    envelope = synthesize_source_policies(ir, level=20, mode_id='bear',
        include_auto_resource_fallback=True)
    assert any(r.action_id == 'enrage:5229' for p in envelope['policies'] for r in p.rules)
