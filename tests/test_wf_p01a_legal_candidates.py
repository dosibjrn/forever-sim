"""WF-P01a: source-bounded legal candidate enumeration, real scorer results."""
from dataclasses import replace
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.level_legality import LevelState, validate_level_state
from src.v2 import legal_candidate_enumeration as c


def test_druid_10_11_envelope_and_real_talent_delta():
    a = c.evaluate_source_candidate_envelope(class_key='druid', level=10)
    b = c.evaluate_source_candidate_envelope(class_key='druid', level=11)
    # New source-backed row-1 families enlarge the legal universe. Counts
    # follow the full executable IR, never a historical Improved-Wrath whitelist.
    assert a['evaluated_count'] == len(a['talent_vectors']) * (len(a['combat_policy_candidates']) + len(a['mode_auto_attack_candidates']))
    assert b['evaluated_count'] == len(b['talent_vectors']) * (len(b['combat_policy_candidates']) + len(b['mode_auto_attack_candidates']))
    assert len(a['talent_vectors']) > 2 and len(b['talent_vectors']) > 3
    assert {} in a['talent_vectors'] and {'improved_wrath': 1} in a['talent_vectors']
    assert {'improved_wrath': 2} in b['talent_vectors']
    assert a['source_only_talent_ids'] and not a['complete_source_talent_coverage']
    assert a['combat_policy_candidates'] == b['combat_policy_candidates']
    assert a['winner']['talents'] == {'improved_wrath': 1}
    assert b['winner']['talents'] == {'improved_wrath': 2}
    assert a['winner']['actions'] == b['winner']['actions'] == ['wrath:5177']
    assert b['winner']['seconds_per_mob'] < a['winner']['seconds_per_mob']
    assert all(x['trace']['status'] == 'EVALUATED' for x in [a['winner'], b['winner']])
    assert not a['complete_optimizer'] and not b['optimization_ready']
    assert a['gear_envelope'] == 'source_actor_naked_only'
    assert not a['all_source_actions_evaluated'] and not a['complete_legal_action_search']
    assert 'bear_form:5487' in a['not_in_canonical_combat_policy']
    assert a['mode_auto_attack_candidates'][0]['entry_action_id'] == 'bear_form:5487'
    assert a['mode_auto_attack_candidates'][0]['exit_action_id'] == 'cancel_mode:bear'
    assert 'healing_touch:rank@8' in a['not_evaluated_source_actions']


def test_real_rank_unlock_and_unavailable_rank_are_not_teleported():
    # 9->10 unlocks Moonfire, Healing Touch, Rejuvenation and Bear; L11 does not.
    a9_ir = build_game_ir_slice(class_key='druid', level=9)
    a10 = c.enumerate_legal_source_candidates(class_key='druid', level=10)
    a11 = c.enumerate_legal_source_candidates(class_key='druid', level=11)
    ids9 = {x.id for x in a9_ir.actions}
    ids10 = {x['id'] for x in a10['source_actions']}
    ids11 = {x['id'] for x in a11['source_actions']}
    assert 'moonfire:8924' in ids10 - ids9
    assert ids10 == ids11
    a13 = c.enumerate_legal_source_candidates(class_key='druid', level=13)
    a14 = c.enumerate_legal_source_candidates(class_key='druid', level=14)
    assert 'wrath:5177' in {x['id'] for x in a13['source_actions']}
    assert 'wrath:5178' in {x['id'] for x in a14['source_actions']}
    assert 'wrath:5177' not in {x['id'] for x in a14['source_actions']}
    with pytest.raises(ValueError, match='unavailable'):
        validate_level_state(LevelState('druid', 10, 'tauren', {}, ('wrath:5178',)))


def test_fail_closed_on_unbounded_search_and_bad_policy(monkeypatch):
    with pytest.raises(ValueError, match='talent candidate envelope'):
        c.enumerate_legal_source_candidates(class_key='druid', level=11, max_talent_vectors=1)
    with pytest.raises(ValueError, match='policy candidate envelope'):
        c.enumerate_legal_source_candidates(class_key='druid', level=10, max_policies=1)
    original = c.build_game_ir_slice
    def poisoned(*, class_key, level):
        ir = original(class_key=class_key, level=level)
        policy = ir.policies[0]
        rule = replace(policy.rules[0], action_id='wrath:5178')
        return replace(ir, policies=(replace(policy, rules=(rule,) + policy.rules[1:]),))
    monkeypatch.setattr(c, 'build_game_ir_slice', poisoned)
    with pytest.raises(ValueError, match='unavailable'):
        c.enumerate_legal_source_candidates(class_key='druid', level=10)
