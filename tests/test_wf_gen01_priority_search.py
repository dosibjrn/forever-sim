"""Generic policy priority exploration is not class/level-special cased."""
import pytest
from src.v2.legal_candidate_enumeration import generate_priority_order_candidates, enumerate_legal_source_candidates


def test_all_orders_and_subsets_are_discovered_without_class_ids():
    options = generate_priority_order_candidates(('alpha', 'beta', 'filler'))
    assert len(options) == 5
    assert set(options) == {
        ('filler',), ('alpha', 'filler'), ('beta', 'filler'),
        ('alpha', 'beta', 'filler'), ('beta', 'alpha', 'filler')
    }
    assert options == generate_priority_order_candidates(('alpha', 'beta', 'filler'))


def test_bounded_search_fails_closed_not_truncated():
    with pytest.raises(ValueError, match='envelope'):
        generate_priority_order_candidates(('a', 'b', 'c', 'filler'), max_policies=5)
    with pytest.raises(ValueError, match='identities'):
        generate_priority_order_candidates(('a', 'a'))


def test_real_game_source_policy_remains_executable_and_not_optimized():
    druid = enumerate_legal_source_candidates(class_key='druid', level=10)
    assert druid['combat_policy_candidates']
    assert not druid['optimization_ready']
    assert druid['policy_envelope'].startswith('source_combat_priority_permutations')
