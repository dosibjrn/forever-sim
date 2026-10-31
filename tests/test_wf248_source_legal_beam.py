"""WF248: legal source frontier is executable, bounded, and unseeded."""
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_search import enumerate_legal_talent_allocations, talent_candidate_id
from src.game.talents import validate_talent_selection
from src.v2.source_legal_beam import legal_point_frontier, _interleave_tree_candidates
from src.v2.source_multi_pull_joint import search_joint_repeated_pulls


def test_empty_l10_parity_with_exhaustive_and_negative_rank():
    ir = build_game_ir_slice(class_key='druid', level=10)
    exact, truncated = enumerate_legal_talent_allocations(ir, level=10, max_candidates=100)
    assert not truncated
    reachable = {talent_candidate_id(a) for a in legal_point_frontier(ir, {}, level=10)}
    assert reachable == {talent_candidate_id(a) for a in exact if sum(a.values()) == 1}
    with pytest.raises(ValueError):
        validate_talent_selection(ir, {'improved_wrath': 2}, level=10)
    with pytest.raises(ValueError):
        legal_point_frontier(ir, {'improved_wrath': 2}, level=10)


def test_full_point_cap_transfers_and_prerequisite_fail_closed():
    ir = build_game_ir_slice(class_key='druid', level=20)
    # Full legal budget; every generated transfer must remain legal.
    full = {'improved_wrath': 5, 'genesis': 5, 'improved_moonfire': 1}
    validate_talent_selection(ir, full, level=20)
    transfers = legal_point_frontier(ir, full, level=20)
    assert transfers
    for allocation in transfers:
        assert sum(allocation.values()) <= 11
        validate_talent_selection(ir, allocation, level=20)
    assert all(talent_candidate_id(a) != talent_candidate_id(full) for a in transfers)
    with pytest.raises(ValueError):
        validate_talent_selection(ir, {'moonfury': 1}, level=20)


def test_source_tree_round_robin_not_largest_incumbent_rank():
    candidates = [({'improved_wrath': 5, 'ferocity': 1}, 'ferocity'),
                  ({'improved_wrath': 5, 'genesis': 1}, 'genesis'),
                  ({'improved_wrath': 5, 'heart_of_the_wild': 1}, 'heart_of_the_wild')]
    ordered = _interleave_tree_candidates(candidates,
        {'ferocity': 'feral', 'genesis': 'balance', 'heart_of_the_wild': 'feral'})
    assert ordered[0]['genesis'] == 1
    assert ordered[1]['ferocity'] == 1


def test_l60_52_family_source_frontier_is_lazy_and_legal():
    ir = build_game_ir_slice(class_key='druid', level=60)
    assert len(ir.talents) == 52
    first = legal_point_frontier(ir, {}, level=60)
    assert first
    assert len(first) <= len(ir.talents)
    for allocation in first:
        validate_talent_selection(ir, allocation, level=60)
    # No 52-dimensional Cartesian allocation materialization is necessary.


def test_cross_class_source_legal_generator_does_not_need_class_lists():
    for key in ('druid', 'mage', 'priest', 'shaman', 'warrior'):
        ir = build_game_ir_slice(class_key=key, level=20)
        candidates = legal_point_frontier(ir, {}, level=20)
        assert len(candidates) == len({talent_candidate_id(c) for c in candidates})
        for candidate in candidates:
            validate_talent_selection(ir, candidate, level=20)


def test_real_repeated_pull_beam_search_and_no_heldout_seeding():
    frozen = {'ferocity': 5, 'heart_of_the_wild': 3,
              'thick_hide': 2, 'savage_fury': 1}
    result = search_joint_repeated_pulls(
        class_key='druid', level=20, pulls=3, max_allocations=32,
        screening_gear_count=1, finalists=1, policy_cap=8,
        held_out_allocation=frozen, strategy='beam')
    winner = result['independent_winner']
    assert result['status'] == 'EVALUATED_BOUNDED'
    assert result['held_out_not_sampled']
    assert result['total_independent_evaluated_allocations'] == 32
    assert winner['seconds_per_mob'] <= 12.564198
    assert winner['talent_allocation'].get('improved_wrath') == 5
    assert result['valid_policy_evaluations'] > 10
    assert winner['best_policy']['pulls']
    assert result['global_optimum_proven'] is False


def test_invalid_budget_and_unsourced_class_fail_closed():
    with pytest.raises(ValueError, match='invalid source legal beam budget'):
        search_joint_repeated_pulls(class_key='druid', level=20,
            max_allocations=0, strategy='beam')
    with pytest.raises(ValueError, match='no canonical source Game IR'):
        search_joint_repeated_pulls(class_key='not_a_class', level=20,
            max_allocations=2, strategy='beam')
