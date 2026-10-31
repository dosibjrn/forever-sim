"""Source joint optimizer tests: independent discovery, held-out fidelity, cross-class."""
import json
from pathlib import Path
from dataclasses import replace

import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.model import PolicyDefinition, PolicyRuleDefinition
from src.game.multi_pull import search_repeated_pull_policies
from src.shared.leveling.objective import representative_hp
from src.v2.source_joint_discovery import _gear_envelope
from src.v2 import source_multi_pull_joint as joint
from tools.wf243_joint_multi_pull_replay import frozen_policy

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / 'fixtures/wf243_heldout_feral_l20.json').read_text())


def test_stratified_independent_sample_never_seeds_heldout_and_covers_trees():
    universe = ({}, {'a': 1}, {'b': 1}, {'c': 1}, {'a': 1, 'b': 1})
    sample, coverage = joint.independent_allocation_sample(
        universe, budget=4, excluded_ids=('talents:a=1;b=1',),
        family_tree={'a': 'first', 'b': 'second', 'c': 'third'})
    assert sample[0] == {}
    assert {'a': 1, 'b': 1} not in sample
    assert {next(iter(a)) for a in sample if a} == {'a', 'b', 'c'}
    assert coverage['unscored_allocations'] == 0


def test_heldout_exact_gear_talents_policy_three_pulls_and_no_implicit_optimization():
    ir = build_game_ir_slice(class_key='druid', level=20)
    gears = _gear_envelope('druid', 20, max_gear_candidates=256,
                           required_level_policy='observed', include_melee_gear=True, ir_slice=ir)
    gear = next(g for g in gears if g['id'] == FIXTURE['gear_id'])
    policy = frozen_policy(FIXTURE['policy'])
    old = joint.replay_exact_challenger(
        class_key='druid', level=20, gear=gear,
        allocation=FIXTURE['talent_allocation'], policy=policy,
        post_combat_action_ids=(FIXTURE['policy']['provenance']['exit_action_id'],), pulls=3)
    assert old['gear_id'] == FIXTURE['gear_id']
    assert old['talent_allocation'] == FIXTURE['talent_allocation']
    assert [r.action_id for r in policy.rules] == ['cat_form:768', 'claw:20']
    assert len(old['pulls']) == 3
    # WF247: sourced same-level hit and qualified target Armor change the scorer.
    assert old['seconds_per_mob'] == pytest.approx(17.887004619287094)


def test_heldout_illegal_action_and_talent_fail_closed():
    ir = build_game_ir_slice(class_key='druid', level=20)
    gear = _gear_envelope('druid', 20, max_gear_candidates=256,
                          required_level_policy='observed', include_melee_gear=True, ir_slice=ir)[0]
    policy = frozen_policy(FIXTURE['policy'])
    illegal = replace(policy, rules=(PolicyRuleDefinition(id='bad', action_id='invented:spell'),))
    with pytest.raises(ValueError, match='unavailable source action'):
        joint.replay_exact_challenger(class_key='druid', level=20, gear=gear,
                                    allocation=FIXTURE['talent_allocation'], policy=illegal)
    with pytest.raises(ValueError):
        joint.replay_exact_challenger(class_key='druid', level=20, gear=gear,
                                    allocation={'ferocity': 999}, policy=policy)


def test_independent_joint_evaluates_distinct_talents_gear_and_policy_on_same_repeated_objective(monkeypatch):
    real_gears = joint._gear_envelope
    def tiny_gears(*args, **kwargs):
        return real_gears(*args, **kwargs)[:2]
    monkeypatch.setattr(joint, '_gear_envelope', tiny_gears)
    result = joint.search_joint_repeated_pulls(
        class_key='druid', level=20, max_allocations=3,
        screening_gear_count=2, finalists=1, pulls=2,
        held_out_allocation=FIXTURE['talent_allocation'], strategy='sample')
    assert result['status'] == 'EVALUATED_BOUNDED'
    assert result['held_out_not_sampled']
    assert result['screened_state_count'] == 6
    assert result['full_gear_envelope_count'] == 2
    assert result['valid_policy_evaluations'] > 2
    assert result['independent_winner']['best_policy']['pulls']
    assert result['global_optimum_proven'] is False
    assert result['source_coverage_complete'] is False


def test_same_stateful_scorer_supports_two_non_druid_classes():
    for class_key in ('priest', 'warrior'):
        ir = build_game_ir_slice(class_key=class_key, level=20)
        result = search_repeated_pull_policies(
            ir_slice=ir, level=20, target_health=representative_hp(20), count=2)
        assert result['winner'] is not None
        assert result['winner']['seconds_per_mob'] > 0
        assert len(result['winner']['pulls']) == 2


def test_missing_source_class_is_explicit_not_fake_empty_winner():
    with pytest.raises(ValueError, match='no canonical source Game IR'):
        joint.search_joint_repeated_pulls(class_key='not_a_class', level=20)
