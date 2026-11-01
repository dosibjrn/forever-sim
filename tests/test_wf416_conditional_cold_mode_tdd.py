"""WF416: conditional talent witnesses must be executable from a cold source stage."""
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.v2.source_bounded_joint_frontier import (
    bounded_full_point_talent_frontier, source_cold_start_stage,
    _source_conditional_aura_policy_witnesses, _prepare_joint_policy_candidate,
)
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate
from tests.test_wf409_talent_unlock_paid_witness_tdd import SOURCE


def _cold_witness():
    with ability_source_scope(SOURCE):
        root = compile_talent_runtime(build_game_ir_slice(class_key='druid', level=30))[0]
        stage = source_cold_start_stage(class_key='druid', level=30,
                                        source_ir=root, gear_role='druid_feral')
        frontier, _ = bounded_full_point_talent_frontier(root, level=30,
            bonus_talent_points=5, max_frontier=16)
        allocation = next(a for a in frontier if a.get('rend_and_tear'))
        selected, _ = apply_talent_selection(root, allocation, level=30,
                                             bonus_talent_points=5)
        label, policy = _source_conditional_aura_policy_witnesses(selected)[0]
        candidate = _prepare_joint_policy_candidate(class_key='druid', level=30,
            stage=stage, allocation=allocation, source_ir=root,
            allow_partial_gear_stats=True, policy_label=label,
            policy=policy, bonus_talent_points=5)
    return candidate


def test_cold_conditional_witness_uses_source_mode_transition_without_caster_opening():
    candidate = _cold_witness()
    assert not candidate.opening, 'independent conditional APL must not inherit caster prefix'
    assert any(rule.action_id == 'cat_form:768' for rule in candidate.policy.rules)
    assert candidate.policy.rules[0].action_id == 'cat_form:768'


def test_cold_conditional_witness_pays_for_4_and_100_real_mobs():
    candidate = _cold_witness()
    for mobs in (4, 100):
        result = evaluate_persistent_candidate(candidate, level=30, mobs=mobs,
                                               max_total_events=200000)
        assert result['status'] == 'COMPLETE', result
        assert result['count'] == mobs
        assert result['source_action_counts'].get('rake:1822', 0) >= mobs
        assert result['source_action_counts'].get('claw:28', 0) >= mobs
        assert result['events'] > mobs
