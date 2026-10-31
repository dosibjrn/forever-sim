"""Cross-class policy frontier and independent legal talent neighborhood acceptance."""
import json
from pathlib import Path

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_search import enumerate_legal_talent_allocations, talent_candidate_id
from src.game.talents import validate_talent_selection
from src.v2.source_policy_search import synthesize_source_policies
from src.v2.source_multi_pull_joint import (
    _source_policy_envelope, _legal_local_neighbors,
    search_joint_repeated_pulls, replay_exact_challenger,
)
from src.v2.source_joint_discovery import _gear_envelope
from tools.wf243_joint_multi_pull_replay import frozen_policy


def test_caster_frontier_does_not_vanish_at_24_policies():
    ir = build_game_ir_slice(class_key='druid', level=20)
    with pytest.raises(ValueError, match='source policy envelope exceeds'):
        synthesize_source_policies(ir, level=20, max_policies=24,
                                   include_auto_resource_fallback=True)
    bounded = synthesize_source_policies(ir, level=20, max_policies=24,
        include_auto_resource_fallback=True, budget_mode='balanced_frontier')
    assert bounded['policy_frontier_truncated'] is True
    assert len(bounded['policies']) == 24
    policies = [tuple(rule.action_id for rule in p.rules) for p in bounded['policies']]
    assert ('wrath:5178',) in policies
    assert ('moonfire:8925', 'wrath:5178') in policies
    assert not bounded['supported_actions_not_represented']
    cases, blockers = _source_policy_envelope(ir, level=20, policy_cap=24)
    assert any(mode is None for _, _, _, mode in cases)
    assert any(mode == 'cat' for _, _, _, mode in cases)
    assert any(mode == 'bear' for _, _, _, mode in cases)
    assert any(row.get('reason') == 'bounded_policy_frontier' for row in blockers)


def test_no_mode_classes_and_mode_classes_share_same_frontier():
    for key in ('mage', 'priest', 'shaman', 'warrior'):
        ir = build_game_ir_slice(class_key=key, level=20)
        policies, _ = _source_policy_envelope(ir, level=20, policy_cap=12)
        assert policies, key
        assert all(p.provenance['budget_mode'] == 'balanced_frontier'
                   for p, _, _, _ in policies)
    with pytest.raises(ValueError, match='unknown policy budget mode'):
        synthesize_source_policies(build_game_ir_slice(class_key='druid', level=20),
                                   level=20, budget_mode='fictional')


def test_legal_local_frontier_excludes_frozen_and_illegal_moves():
    ir = build_game_ir_slice(class_key='druid', level=20)
    allocations, truncated = enumerate_legal_talent_allocations(ir, level=20,
                                                                 max_candidates=200000)
    assert not truncated
    incumbent = {'genesis': 1, 'improved_wrath': 4, 'improved_moonfire': 2}
    assert any(a == incumbent for a in allocations)
    frozen = {'ferocity': 5, 'heart_of_the_wild': 3,
              'thick_hide': 2, 'savage_fury': 1}
    excluded = {talent_candidate_id(incumbent), talent_candidate_id(frozen)}
    neighbors = _legal_local_neighbors(allocations, incumbent,
                                      excluded_ids=excluded, budget=24)
    assert len(neighbors) == 24
    assert len({talent_candidate_id(a) for a in neighbors}) == len(neighbors)
    for candidate in neighbors:
        assert talent_candidate_id(candidate) not in excluded
        validate_talent_selection(ir, candidate, level=20)
        assert sum(abs(candidate.get(k, 0) - incumbent.get(k, 0))
                   for k in set(candidate) | set(incumbent)) <= 2
    assert _legal_local_neighbors(allocations, incumbent, budget=0) == []
    with pytest.raises(ValueError, match='negative'):
        _legal_local_neighbors(allocations, incumbent, budget=-1)


def test_real_joint_e2e_and_exact_heldout_challenger():
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root/'fixtures/wf243_heldout_feral_l20.json').read_text())
    search = search_joint_repeated_pulls(class_key='druid', level=20,
        max_allocations=4, screening_gear_count=1, finalists=1, policy_cap=12,
        held_out_allocation=fixture['talent_allocation'], refinement_budget=2,
        refinement_rounds=1, strategy='sample')
    assert search['independent_winner']['seconds_per_mob'] > 0
    assert search['local_refinement_evaluated_allocations'] == 2
    assert search['total_independent_evaluated_allocations'] == 6
    assert search['held_out_not_sampled']
    assert search['independent_winner']['best_policy']['pulls']
    ir = build_game_ir_slice(class_key='druid', level=20)
    gears = _gear_envelope('druid', 20, max_gear_candidates=256,
        required_level_policy='observed', include_melee_gear=True, ir_slice=ir)
    gear = next(g for g in gears if g['id'] == fixture['gear_id'])
    old = replay_exact_challenger(class_key='druid', level=20, gear=gear,
        allocation=fixture['talent_allocation'], policy=frozen_policy(fixture['policy']),
        pulls=3, post_combat_action_ids=(fixture['policy']['provenance']['exit_action_id'],))
    assert old['seconds_per_mob'] == pytest.approx(13.15138592750533)
    assert old['talent_allocation'] == fixture['talent_allocation']
    assert search['independent_winner']['talent_allocation'] != fixture['talent_allocation']
