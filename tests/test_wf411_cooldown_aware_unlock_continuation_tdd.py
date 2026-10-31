"""WF411 RED: a talent unlock witness must finish a paid persistent multi-mob screen."""
from dataclasses import replace

import pytest

from src.game.model import PolicyCondition
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.policy import condition_matches
from src.game.data.forever.source_db_scope import ability_source_scope
from src.game.talents import apply_talent_selection
from src.v2.source_bounded_joint_frontier import (
    source_talent_unlock_witnesses, _prepare_joint_policy_candidate,
)
from src.v2.source_persistent_joint_finalists import evaluate_persistent_candidate
from tests.test_wf409_talent_unlock_paid_witness_tdd import (
    _source, _stage, ALLOCATION, SOURCE,
)


def _witness():
    root = _source()
    selected, _ = apply_talent_selection(root, ALLOCATION, level=30)
    return root, selected, next(w for w in source_talent_unlock_witnesses(root, selected, _stage())
                                if w['action_id'] == 'primal_bite:25')


def test_cooldown_guard_uses_real_actor_action_cooldown_and_fails_closed():
    with ability_source_scope(SOURCE):
        _, selected, _ = _witness()
        actor = ActorState.from_ir(selected.actor, selected.resources, selected.modes)
        runtime = CombatRuntime(actor=actor, target=TargetState.with_health('target', 1000.))
        action = next(a for a in selected.actions if a.id == 'enrage:5229')
        cond = PolicyCondition(kind='cooldown_ready', field=action.id, operator='eq', value=True)
        assert condition_matches(cond, action=action, runtime=runtime) is True
        actor.cooldown_ready_s[action.id] = actor.current_time_s + 30.
        assert condition_matches(cond, action=action, runtime=runtime) is False
        actor.current_time_s += 30.
        assert condition_matches(cond, action=action, runtime=runtime) is True
        with pytest.raises(ValueError, match='COOLDOWN_.*ACTION'):
            condition_matches(replace(cond, field='not_in_source_ir'), action=action, runtime=runtime)


def test_scratch_unlock_policy_is_independent_of_legacy_cat_opening():
    with ability_source_scope(SOURCE):
        root, selected, witness = _witness()
        candidate = _prepare_joint_policy_candidate(
            class_key='druid', level=30, stage=_stage(), allocation=ALLOCATION,
            source_ir=root, allow_partial_gear_stats=True,
            policy_label='talent_unlock:primal_bite:25', policy=witness['policy'])
        assert candidate.opening == (), 'source-scratch witness must not replay unrelated historical opening'
        assert any(c.kind == 'cooldown_ready' for rule in candidate.policy.rules
                   for c in rule.conditions)
        assert any(rule.action_id == 'claw:28' for rule in candidate.policy.rules)
        assert any(rule.action_id == 'cancel_mode:bear' for rule in candidate.policy.rules)


def test_source_unlock_witness_completes_paid_four_mobs_with_real_bite_cast():
    with ability_source_scope(SOURCE):
        root, _, witness = _witness()
        candidate = _prepare_joint_policy_candidate(
            class_key='druid', level=30, stage=_stage(), allocation=ALLOCATION,
            source_ir=root, allow_partial_gear_stats=True,
            policy_label='talent_unlock:primal_bite:25', policy=witness['policy'])
        result = evaluate_persistent_candidate(candidate, level=30, mobs=4,
                                               max_total_events=200000)
        assert result['status'] == 'COMPLETE', result
        assert result['count'] == 4
        assert result['source_action_counts']['primal_bite:25'] > 0
        assert result['source_action_counts']['enrage:5229'] > 0
        assert result['source_action_counts']['claw:28'] > 0
        assert result['events'] > 0


def test_periodic_resource_producer_is_not_abandoned_before_its_real_ticks():
    with ability_source_scope(SOURCE):
        root, selected, witness = _witness()
        enrage = next(a for a in selected.actions if a.id == 'enrage:5229')
        from src.game.model import PeriodicResourceEffect
        aura_ids = {e.aura_id for e in enrage.effects if isinstance(e, PeriodicResourceEffect)}
        assert aura_ids
        exits = [rule for rule in witness['policy'].rules if rule.action_id == 'cancel_mode:bear']
        assert exits
        assert any(c.kind == 'aura_missing' and c.scope == 'actor' and c.aura_id in aura_ids
                   for c in exits[0].conditions)
        candidate = _prepare_joint_policy_candidate(
            class_key='druid', level=30, stage=_stage(), allocation=ALLOCATION,
            source_ir=root, allow_partial_gear_stats=True,
            policy_label='talent_unlock:primal_bite:25', policy=witness['policy'])
        result = evaluate_persistent_candidate(candidate, level=30, mobs=1,
                                               max_total_events=200000)
        assert result['status'] == 'COMPLETE', result
        assert result['source_action_counts'].get('primal_bite:25', 0) > 0
