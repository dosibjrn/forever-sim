"""Concurrent 2D pack execution through the existing 100-mob objective (RED)."""
from dataclasses import replace

import pytest

from src.game.data.forever import build_game_ir_slice
from src.game.model import ActionDefinition, DamageEffect, PolicyDefinition, PolicyRuleDefinition
from src.game.multi_pull import evaluate_repeated_pulls
from src.game.policy import execute_priority_policy
from src.game.runtime import ActorState, CombatRuntime, TargetState


def _one_hit_fixture():
    ir = build_game_ir_slice(class_key='druid', level=30)
    source_wrath = next(a for a in ir.actions if a.family_key == 'wrath')
    hit = replace(source_wrath, costs=(), cast_time_s=0, gcd_s=0, cooldown_s=0,
        effects=(DamageEffect(effect_type='damage', school='nature',
        target='enemy', base_min=100, base_max=100),))
    policy = PolicyDefinition(id='fixture:policy', label='Hit until pack dies',
        rules=(PolicyRuleDefinition(id='hit', action_id=hit.id),))
    return replace(ir, actions=(hit,), policies=(policy,), auto_attacks=(),
        incoming_attacks=(), triggers=(), companions=(), timed_summons=()), policy


def test_apl_switches_to_next_alive_enemy_in_same_2d_encounter():
    ir, policy = _one_hit_fixture()
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    targets = [TargetState.with_health('m0', 100), TargetState.with_health('m1', 100)]
    runtime = CombatRuntime(actor=actor, target=targets[0], other_targets=(targets[1],),
        spatial_positions_yards={'m0':(0,0),'m1':(20,0)}, enemy_move_speed_yards_s=7)
    runtime.engage_target('m1')
    result = execute_priority_policy(policy=policy, actions=ir.actions, runtime=runtime, max_actions=12)
    assert result.timeline.target_defeated
    assert len(result.selected_actions) == 2
    assert result.timeline.target_death_s is not None
    assert all(not t.alive for t in targets)


def test_four_mobs_are_two_persistent_concurrent_packs_not_four_serial_pulls():
    ir, policy = _one_hit_fixture()
    result = evaluate_repeated_pulls(ir_slice=ir, policy=policy, level=30,
        target_health=100, count=4, pack_size=2, schedule_incoming_attacks=False)
    assert len(result.pulls) == 2
    assert [p['mob_count'] for p in result.pulls] == [2,2]
    assert [len(p['selected_actions']) for p in result.pulls] == [2,2]
    assert all(p['pack_all_defeated'] for p in result.pulls)
    assert result.seconds_per_mob == pytest.approx((result.end_time_s-result.start_time_s)/4)


def test_real_source_100_mob_two_target_packs_charge_actual_recovery():
    ir = build_game_ir_slice(class_key='druid', level=30)
    wrath = next(a for a in ir.actions if a.family_key == 'wrath')
    policy = PolicyDefinition(id='source:wrath_only', label='Wrath only',
        rules=(PolicyRuleDefinition(id='wrath',action_id=wrath.id),))
    result = evaluate_repeated_pulls(ir_slice=ir, policy=policy, level=30,
        target_health=60, count=100, pack_size=2,
        recovery_mode='always', schedule_incoming_attacks=True)
    assert len(result.pulls) == 50
    assert all(p['pack_all_defeated'] and p['mob_count']==2 for p in result.pulls)
    assert all(p['event_transitions'] > 0 for p in result.pulls)
    assert sum(p['recovery_s'] for p in result.pulls) > 0
    assert result.seconds_per_mob > 0
