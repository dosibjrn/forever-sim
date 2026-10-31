"""Functional expansion of the real source gear candidate search."""
import pytest
from src.v2.source_joint_discovery import _gear_envelope, evaluate_bounded_joint_discovery


def test_pairwise_weight_search_discovers_additional_actual_equipment():
    original = _gear_envelope('druid', 20, max_gear_candidates=32)
    expanded = _gear_envelope('druid', 20, max_gear_candidates=32, gear_weight_order=2)
    original_ids = {r['id'] for r in original}
    expanded_ids = {r['id'] for r in expanded}
    assert original_ids <= expanded_ids
    assert len(expanded_ids - original_ids) > 0, 'no new real sourced equipment found'
    for candidate in expanded:
        assert candidate['selection'].slots
        for slot, item in candidate['selection'].slots.items():
            assert item['item_id'] and item['name']
            assert item['effective_level'] is None or item['effective_level'] <= 20


def test_pairwise_search_cap_fails_closed_instead_of_clipping():
    with pytest.raises(ValueError, match='gear candidate envelope exceeds explicit bound'):
        _gear_envelope('druid', 20, max_gear_candidates=1, gear_weight_order=2)


@pytest.mark.parametrize('order', [0, 5, -1, 1.5, True])
def test_invalid_weight_order_rejected(order):
    with pytest.raises(ValueError, match='gear weight combination order'):
        _gear_envelope('druid', 20, max_gear_candidates=32, gear_weight_order=order)


def test_joint_search_rejects_underbudgeted_pairwise_run():
    with pytest.raises(ValueError, match='gear candidate envelope exceeds explicit bound|joint gear x talent state envelope|executable talent candidate envelope exceeds explicit bound'):
        evaluate_bounded_joint_discovery(class_key='druid', level=20,
                                          gear_weight_order=2, max_gear_candidates=1)
