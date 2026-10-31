"""WF409: a P4 talent-unlocked action must be generated AND executed, not listed."""
from dataclasses import replace
from pathlib import Path
import json

from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.v2.source_persistent_joint_finalists import prepare_candidate, evaluate_persistent_candidate
from src.v2.source_bounded_joint_frontier import source_talent_unlock_witnesses

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/forever/staged_druid_l30_talents_70338.sqlite'
ALLOCATION = {
    'ferocity': 5, 'heart_of_the_wild': 5, 'feral_instinct': 3,
    'thick_hide': 3, 'savage_fury': 2, 'feral_swiftness': 2,
    'primal_bite': 1,
}


def _source():
    return compile_talent_runtime(build_game_ir_slice(class_key='druid', level=30))[0]


def _stage():
    return json.loads((ROOT / 'evidence/wf360/WF360_L30_P4_30S.json').read_text())['winner_stage']


def test_witness_is_from_actual_unlocked_ir_and_paid_mode_path():
    with ability_source_scope(SOURCE):
        root = _source()
        talented, _ = apply_talent_selection(root, ALLOCATION, level=30)
        witnesses = source_talent_unlock_witnesses(root, talented, _stage())
        found = [w for w in witnesses if w['action_id'] == 'primal_bite:25']
        assert len(found) == 1
        witness = found[0]
        assert witness['source_talent_id'] == 'primal_bite'
        assert witness['mode_path'] == ('cancel_mode:cat', 'bear_form:5487')
        assert witness['policy'].provenance['source_policy_seeded'] is False
        ids = [r.action_id for r in witness['policy'].rules]
        assert 'primal_bite:25' in ids
        assert 'enrage:5229' in ids  # sourced rage producer, not free rage
        assert set(witness['mode_path']).issubset(ids)


def test_no_talent_unlock_means_no_witness_or_illegal_action():
    with ability_source_scope(SOURCE):
        root = _source()
        locked, _ = apply_talent_selection(root, {}, level=30)
        assert not any(a.id == 'primal_bite:25' for a in locked.actions)
        assert source_talent_unlock_witnesses(root, locked, _stage()) == ()


def test_witness_action_is_really_executed_in_canonical_runtime():
    with ability_source_scope(SOURCE):
        root = _source()
        talented, _ = apply_talent_selection(root, ALLOCATION, level=30)
        witness = next(w for w in source_talent_unlock_witnesses(root, talented, _stage())
                       if w['action_id'] == 'primal_bite:25')
        # A source-generated witness is an independent APL: do not attach the
        # historical Cat Form + Claw opening from the incumbent stage.
        from src.v2.source_bounded_joint_frontier import _prepare_joint_policy_candidate
        candidate = _prepare_joint_policy_candidate(class_key='druid', level=30,
            stage=_stage(), allocation=ALLOCATION, source_ir=root,
            allow_partial_gear_stats=True, policy_label='talent_unlock:primal_bite:25',
            policy=witness['policy'])
        result = evaluate_persistent_candidate(candidate, level=30, mobs=4,
                                               max_total_events=200000)
        assert result['status'] == 'COMPLETE', result
        assert result['source_action_counts']['primal_bite:25'] > 0
        assert result['source_action_counts']['cancel_mode:cat'] > 0
        assert result['source_action_counts']['bear_form:5487'] > 0


def test_full_point_frontier_reserves_reachable_source_unlock():
    from src.v2.source_bounded_joint_frontier import bounded_full_point_talent_frontier
    from src.game.talents import validate_talent_selection
    with ability_source_scope(SOURCE):
        root = _source()
        for budget in (4, 64):
            allocations, proof = bounded_full_point_talent_frontier(root, level=30,
                                                                    max_frontier=budget)
            unlocked = [a for a in allocations if a.get('primal_bite') == 1]
            assert unlocked, (budget, proof)
            for allocation in unlocked:
                assert sum(allocation.values()) == 21
                validate_talent_selection(root, allocation, level=30)
                selected, _ = apply_talent_selection(root, allocation, level=30)
                assert any(a.id == 'primal_bite:25' for a in selected.actions)


def test_paid_joint_search_actually_screens_talent_unlocked_action():
    from src.v2.source_bounded_joint_frontier import search_bounded_joint_frontier
    with ability_source_scope(SOURCE):
        root = _source()
        result = search_bounded_joint_frontier(
            class_key='druid', level=30, source_ir=root, seed_stage=_stage(),
            max_talents=4, max_gear_moves=0, max_policies=2,
            max_recovery_policies=1, max_paid_builds=4, max_cpu_s=8.,
            per_candidate_wall_s=2., screen_mobs=4, finalist_mobs=100,
            screen_then_finalists=True, max_finalists=1,
            proposal_strategy='diagonal', allow_partial_gear_stats=True)
        assert result['wall_s'] <= 8.5
        witnesses = [row for row in result['rows']
                     if row['policy_origin'] == 'talent_unlock:primal_bite:25']
        assert witnesses, result['rows']
        assert witnesses[0]['allocation'].get('primal_bite') == 1
        assert witnesses[0]['source_action_counts']['primal_bite:25'] > 0
        assert result['p4_talent_unlock_coverage']['primal_bite:25']['executed_casts'] > 0


def test_complete_unlock_screen_can_claim_paid_p4_coverage():
    from src.v2.source_bounded_joint_frontier import search_bounded_joint_frontier
    with ability_source_scope(SOURCE):
        result = search_bounded_joint_frontier(
            class_key='druid', level=30, source_ir=_source(), seed_stage=_stage(),
            max_talents=4, max_gear_moves=0, max_policies=2,
            max_recovery_policies=1, max_paid_builds=2, max_cpu_s=6.,
            per_candidate_wall_s=2., screen_mobs=4, finalist_mobs=100,
            screen_then_finalists=True, max_finalists=1,
            proposal_strategy='diagonal', allow_partial_gear_stats=True)
        record = result['p4_talent_unlock_coverage']['primal_bite:25']
        assert record['executed_casts'] > 0
        assert record['complete_paid_screens'] >= 1
        assert record['status'] == 'EXECUTED_IN_COMPLETE_PAID_SCREEN'
        assert result['p4_talent_unlock_coverage_pass'] is True
