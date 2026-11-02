"""Work2: charge real recovery CombatRuntime transitions in the paid 2D objective.

Use canonical Druid L30 spell facts and the production runtime. Only the
recovery *decision* is fixed to one legal sourced direct heal, so this tests
accounting and the event ceiling rather than the policy optimizer's ranking.
These are bounded regressions, not a P4/P5/P6 acceptance run.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.game import recovery
from src.game.data.forever import build_game_ir_slice
from src.game.model import HealEffect, PeriodicHealEffect, PolicyDefinition, PolicyRuleDefinition
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.recovery_between_pulls import BetweenPullPolicy, between_pull_recovery
from src.game.runtime import ActorState, action_eligibility
from src.game.runtime.simulator import EventTransitionBudgetExceeded


def _source_heal_ir(monkeypatch):
    ir = build_game_ir_slice(class_key="druid", level=30)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    heals = [
        action for action in ir.actions
        if any(isinstance(effect, HealEffect) for effect in action.effects)
        and not any(isinstance(effect, PeriodicHealEffect) for effect in action.effects)
        and action_eligibility(action=action, actor=actor).eligible
    ]
    assert heals, "source L30 Druid must offer a legal direct heal for this regression"
    heal = heals[0]
    wrath = next(action for action in ir.actions if action.family_key == "wrath")
    # Restrict only the healing decision: the spell and its runtime remain sourced.
    ir = replace(ir, actions=(wrath, heal))
    monkeypatch.setattr(recovery, "solve_recovery",
                        lambda *args, **kwargs: SimpleNamespace(
                            heal_name=heal.id, heal_casts=1))
    return ir, heal, wrath


def test_real_source_direct_heal_recovery_reports_and_bounds_its_events(monkeypatch):
    ir, heal, _ = _source_heal_ir(monkeypatch)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.resources["health"] = 1.
    kwargs = dict(actor=actor, level=30, actions=(heal,),
                  start_time_s=float(actor.current_time_s))
    with pytest.raises(EventTransitionBudgetExceeded, match="BUDGET_EVENT_TRANSITIONS"):
        recovery.recover_actor_to_full(**kwargs, max_new_events=0)

    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.resources["health"] = 1.
    result = recovery.recover_actor_to_full(
        actor=actor, level=30, actions=(heal,),
        start_time_s=float(actor.current_time_s), max_new_events=100000)
    assert result.heal_casts == 1
    assert result.runtime_events > 0
    assert result.runtime_events >= len(result.heal_events)
    assert result.as_dict()["runtime_events"] == result.runtime_events


def test_real_source_paid_pack_counts_recovery_and_rejects_one_event_short(monkeypatch):
    ir, heal, wrath = _source_heal_ir(monkeypatch)
    policy = PolicyDefinition(
        id="work2:recovery:wrath", label="Source Wrath",
        rules=(PolicyRuleDefinition(id="work2:recovery:rule", action_id=wrath.id),))
    initial = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    kwargs = dict(ir_slice=ir, policy=policy, level=30, target_health=20.,
                  count=1, pack_size=1, schedule_incoming_attacks=False,
                  recovery_action_ids=(heal.id,),
                  prepared_first_pull_resources={"health": 1.})
    completed = evaluate_repeated_pulls(**kwargs, max_total_events=100000)
    pull = completed.pulls[0]
    assert pull["ordinary_recovery_runtime_events"] > 0
    assert pull["event_transitions"] == sum(pull[key] for key in (
        "combat_runtime_events", "maintenance_runtime_events",
        "between_pull_runtime_events", "mode_exit_runtime_events",
        "ordinary_recovery_runtime_events", "travel_runtime_events"))
    with pytest.raises(EventTransitionBudgetExceeded, match="BUDGET_EVENT_TRANSITIONS"):
        evaluate_repeated_pulls(**kwargs, max_total_events=pull["event_transitions"]-1)
    exact = evaluate_repeated_pulls(**kwargs, max_total_events=pull["event_transitions"])
    assert exact.pulls[0]["event_transitions"] == pull["event_transitions"]


def test_sourced_between_pull_full_recovery_charges_runtime_events(monkeypatch):
    ir, _, _ = _source_heal_ir(monkeypatch)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.resources["health"] = 1.
    kwargs = dict(ir=ir, level=30, mob_index=0, mob_count=1,
                  policy=BetweenPullPolicy(health_fraction=.9, mana_fraction=.9))
    with pytest.raises(EventTransitionBudgetExceeded, match="BUDGET_EVENT_TRANSITIONS"):
        between_pull_recovery(actor=actor, max_new_events=0, **kwargs)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.resources["health"] = 1.
    step = between_pull_recovery(actor=actor, max_new_events=100000, **kwargs)
    assert step["full_recovery"]
    assert step["events"] > 0
