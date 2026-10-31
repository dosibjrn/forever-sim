"""Real source spells and combat/recovery/next-pull continuation regression."""
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.recovery import recover_actor_to_full
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.shared.leveling.objective import representative_hp


def _druid_recovery():
    ir = build_game_ir_slice(class_key='druid', level=20)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.resources.update({'health': 250., 'mana': 400.})
    result = recover_actor_to_full(actor=actor, level=20, actions=ir.actions, start_time_s=10.)
    return ir, actor, result


def test_real_rejuvenation_carries_source_events_to_next_pull_exactly_once():
    ir, actor, rec = _druid_recovery()
    assert rec.provenance['heal_action_sequence'] == ['rejuvenation:rank@16']
    assert len(actor.pending_actor_periodic_events) == 3
    assert rec.provenance['pending_hot_auras_carried_into_next_pull']
    next_pull = CombatRuntime(actor=actor, target=TargetState.with_health('next', 100.))
    assert not actor.pending_actor_periodic_events  # MOVE, not copy
    actor.deplete('health', 100.)
    next_pull.advance_to(23.)
    heals = [e for e in next_pull.trace if e.kind == 'Heal' and e.payload.get('periodic')]
    assert [e.time_s for e in heals] == [19., 22.]
    assert [e.payload['amount'] for e in heals] == pytest.approx([29., 29.])
    assert actor.resource_amount('health') == pytest.approx(458.)
    assert not actor.active_auras
    assert not next_pull.persist_actor_periodics()


def test_recovery_with_inherited_hot_does_not_lose_or_duplicate_ticks():
    ir, actor, _ = _druid_recovery()
    actor.deplete('health', 75.)
    result = recover_actor_to_full(actor=actor, level=20, actions=(),
                                   start_time_s=actor.current_time_s)
    assert result.provenance['heal_action_sequence'] == []
    # Remaining old ticks execute once while food/water progresses.
    ticks = [e for e in result.heal_events if e['kind'] == 'Heal' and e['payload'].get('periodic')]
    assert len(ticks) == 1
    assert actor.resource_amount('health') == pytest.approx(actor.resource_capacity['health'])
    assert sum(e.kind == 'PeriodicTick' for e in actor.pending_actor_periodic_events) == 1
    follow = CombatRuntime(actor=actor, target=TargetState.with_health('follow', 100.))
    actor.deplete('health', 50.)
    follow.advance_to(23.)
    assert len([e for e in follow.trace if e.kind == 'Heal' and e.payload.get('periodic')]) == 1


def test_corrupt_or_stale_continuation_is_rejected_instead_of_free_heal():
    ir, actor, _ = _druid_recovery()
    actor.pending_actor_periodic_actions.clear()
    with pytest.raises(ValueError, match='matching source action'):
        CombatRuntime(actor=actor, target=TargetState.with_health('next', 100.))


def test_actual_three_pulls_have_carried_healing_and_lower_cycle_time():
    ir = build_game_ir_slice(class_key='druid', level=20)
    kwargs = dict(ir_slice=ir, policy=ir.policies[1], level=20,
                  target_health=representative_hp(20), count=3,
                  pre_combat_action_ids=('cat_form:768',),
                  post_combat_action_ids=('cancel_mode:cat',))
    real = evaluate_repeated_pulls(**kwargs)
    control = evaluate_repeated_pulls(**kwargs, carry_actor_periodics=False)
    assert real.pulls[0]['pending_ticks_after_recovery'] > 0
    assert real.pulls[1]['carried_ticks_at_start'] > 0
    assert real.pulls[1]['carried_heal_events_during_combat'] > 0
    assert real.seconds_per_mob < control.seconds_per_mob
    assert all(p['health_after_recovery'] == pytest.approx(500.) for p in real.pulls)
    assert all(p['mana_after_recovery'] == pytest.approx(614.) for p in real.pulls)


def test_target_dot_does_not_cross_into_fresh_enemy():
    ir = build_game_ir_slice(class_key='druid', level=20)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    moonfire = next(a for a in ir.actions if a.family_key == 'moonfire')
    runtime = CombatRuntime(actor=actor, target=TargetState.with_health('enemy1', 300.))
    runtime.schedule_action(moonfire)
    runtime.advance_to(1.)
    assert runtime.target.active_auras
    assert not runtime.persist_actor_periodics()
    fresh = CombatRuntime(actor=actor, target=TargetState.with_health('enemy2', 300.))
    fresh.advance_to(5.)
    assert fresh.target.health == pytest.approx(300.)
    assert not fresh.target.active_auras


def test_actor_hot_from_combat_survives_enemy_death_into_recovery():
    ir = build_game_ir_slice(class_key='druid', level=20)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    target = TargetState.with_health('enemy', 30.)
    runtime = CombatRuntime(actor=actor, target=target,
                            incoming_attacks=ir.incoming_attacks,
                            mitigation_rules=ir.mitigation_rules)
    hot = next(a for a in ir.actions if a.family_key == 'rejuvenation')
    wrath = next(a for a in ir.actions if a.family_key == 'wrath')
    runtime.schedule_action(hot)
    runtime.advance_to(actor.gcd_ready_s)
    runtime.schedule_action(wrath)
    runtime.run_until_idle()
    assert not target.alive
    assert actor.pending_actor_periodic_events
    assert all(e.payload.get('aura_scope') == 'actor' for e in actor.pending_actor_periodic_events)
    recovery = recover_actor_to_full(actor=actor, level=20, actions=(),
                                     start_time_s=actor.current_time_s)
    assert recovery.total_s >= 0
    assert recovery.provenance['pending_hot_auras_carried_into_next_pull']


def test_priest_renew_uses_same_cross_pull_runtime_without_class_dispatch():
    ir = build_game_ir_slice(class_key='priest', level=20)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.resources.update({'health': 250., 'mana': 490.})
    renew = next(a for a in ir.actions if a.family_key == 'renew')
    result = recover_actor_to_full(actor=actor, level=20, actions=(renew,), start_time_s=0.)
    assert result.provenance['heal_action_sequence'] == [renew.id]
    assert actor.pending_actor_periodic_events
    next_pull = CombatRuntime(actor=actor, target=TargetState.with_health('new', 100.))
    actor.deplete('health', 50.)
    next_pull.advance_to(actor.current_time_s + 5.)
    assert any(e.kind == 'Heal' and e.payload.get('periodic') for e in next_pull.trace)


def test_all_source_policy_candidates_enter_the_repeated_pull_comparison():
    from src.game.multi_pull import search_repeated_pull_policies
    ir = build_game_ir_slice(class_key='druid', level=20)
    result = search_repeated_pull_policies(
        ir_slice=ir, level=20, target_health=representative_hp(20))
    assert result['candidate_count'] == len(ir.policies) == result['evaluated_count']
    assert result['winner']['policy_id'] == ir.policies[1].id
    assert result['winner']['seconds_per_mob'] == pytest.approx(18.319565217391304)
    assert result['global_optimum_proven'] is False
