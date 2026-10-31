"""Real ratio-expanded source-gear candidate generation (no new engine)."""
import math
from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.v2.source_joint_discovery import _gear_envelope, evaluate_bounded_joint_discovery


def test_ratio_expansion_is_strict_superset_of_unit_pairwise_druid():
    unit = _gear_envelope('druid', 20, max_gear_candidates=64, gear_weight_order=2)
    expanded = _gear_envelope('druid', 20, max_gear_candidates=64,
                              gear_weight_order=2, gear_weight_ratios=(0.5, 1., 2.))
    assert {r['id'] for r in unit} < {r['id'] for r in expanded}
    assert len({r['id'] for r in expanded}) == len(expanded)
    assert any(any(w != 1 for w in r['weight_vector'].values()) for r in expanded)
    assert all(r['selection'].slots and all(i['item_id'] for i in r['selection'].slots.values()) for r in expanded)


def test_ratio_expansion_is_generic_across_classes():
    unit = _gear_envelope('mage', 20, max_gear_candidates=64, gear_weight_order=2)
    expanded = _gear_envelope('mage', 20, max_gear_candidates=64,
                              gear_weight_order=2, gear_weight_ratios=(0.5, 1., 2.))
    assert {r['id'] for r in unit} < {r['id'] for r in expanded}


def test_ratio_order_canonical_and_reproducible():
    x = _gear_envelope('druid', 20, max_gear_candidates=64, gear_weight_order=2,
                       gear_weight_ratios=(2., 1., 0.5))
    y = _gear_envelope('druid', 20, max_gear_candidates=64, gear_weight_order=2,
                       gear_weight_ratios=(0.5, 1., 2.))
    assert [(r['id'], r['weight_vector']) for r in x] == [(r['id'], r['weight_vector']) for r in y]


@pytest.mark.parametrize('ratios', [(), (0.5,), (1., 1.), (0., 1.), (-1., 1.),
                                   (float('nan'), 1.), (float('inf'), 1.),
                                   ('1',), (True, 1.), (1., 2., 3., 4., 5., 6.)])
def test_invalid_ratio_vectors_fail_closed(ratios):
    with pytest.raises(ValueError, match='gear weight ratios'):
        _gear_envelope('druid', 20, max_gear_candidates=64, gear_weight_order=2,
                       gear_weight_ratios=ratios)


def test_ratio_search_fails_closed_on_insufficient_gear_cap():
    with pytest.raises(ValueError, match='gear candidate envelope exceeds explicit bound'):
        _gear_envelope('druid', 20, max_gear_candidates=10, gear_weight_order=2,
                       gear_weight_ratios=(0.5, 1., 2.))


def test_ratio_search_fails_closed_on_insufficient_state_cap():
    with pytest.raises(ValueError, match='joint gear x talent state envelope exceeds explicit bound|executable talent candidate envelope exceeds explicit bound'):
        evaluate_bounded_joint_discovery(class_key='druid', level=20, gear_weight_order=2,
                                         gear_weight_ratios=(0.5, 1., 2.),
                                         max_gear_candidates=32, max_states=60,
                                         max_talent_candidates=512)


def test_ratio_search_fails_closed_on_excessive_raw_vector_count():
    with pytest.raises(ValueError, match='gear weight vector envelope exceeds explicit bound'):
        _gear_envelope('druid', 20, max_gear_candidates=1000, gear_weight_order=4,
                       gear_weight_ratios=(0.25, 0.5, 1., 2., 4.))


def test_real_druid_l20_ratio_search_rediscover_og_and_improve():
    """Fresh generic search, not seeded by OG; replayable .219 comparison."""
    from pathlib import Path
    import json
    old = json.loads((Path(__file__).resolve().parents[1] /
                      'WF_GEN03A5_DRUID_L20_EXPANDED_RUN_v0.11.48.219.json').read_text())
    source = build_game_ir_slice(class_key='druid', level=20)
    # This 2026-10-09 regression compares the original single-family search,
    # not the enlarged current SQLite talent universe.
    historical = replace(source, talents=tuple(t for t in source.talents
                                                 if t.id == 'improved_wrath'))
    new = evaluate_bounded_joint_discovery(
        class_key='druid', level=20, ir_slice=historical, gear_weight_order=2,
        gear_weight_ratios=(0.5, 1., 2.), max_gear_candidates=32, max_states=128)
    assert new['gear_candidate_count'] > old['gear_candidate_count']
    assert new['evaluated_state_count'] > old['evaluated_state_count']
    assert new['winner']['score_s_per_mob'] < old['winner']['score_s_per_mob']
    assert any(s['gear_id'] == old['winner']['gear_id'] and
               s['talent_id'] == old['winner']['talent_id'] and
               abs(s['score_s_per_mob'] - old['winner']['score_s_per_mob']) < 1e-8
               for s in (new['winner'], *new['alternatives']))
    assert len(new['winner']['gear_slots']) >= 10
    assert new['winner']['talent_id']
    assert new['winner']['best_policy']['selected_actions']
    assert new['optimization_ready'] is False
    assert new['gear_acquisition_verified'] is False
