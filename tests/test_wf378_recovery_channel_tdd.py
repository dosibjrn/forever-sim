"""RED: an actual actor-stats mana channel must compete with vendor water.

This is a generic recovery contract, not a special Mage-only solver.
"""
from src.game.data.forever.mage import build_source_slice
from src.game.recovery import recover_actor_to_full
from src.game.runtime import ActorState


def _setup():
    ir = build_source_slice(30)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.stats['spirit'] = 60.
    actor.resources['mana'] = 0.
    actor.resource_capacity['mana'] = 750.
    actor.resources['health'] = actor.resource_capacity['health']
    return actor, next(a for a in ir.actions if a.family_key == 'evocation')


def test_spirit_channel_competes_with_vendor_water_and_persists_cooldown():
    plain, _ = _setup()
    water = recover_actor_to_full(actor=plain, level=30, actions=(), start_time_s=0.)
    actor, channel = _setup()
    result = recover_actor_to_full(actor=actor, level=30, actions=(channel,), start_time_s=0.)
    assert result.total_s < water.total_s
    assert result.total_s == 4.
    assert actor.resource_amount('mana') == 750.
    assert actor.cooldown_ready_s[channel.id] == 480.
    assert result.provenance['resource_recovery_decision']['selected_action_id'] == channel.id
    actor.resources['mana'] = 0.
    second = recover_actor_to_full(actor=actor, level=30, actions=(channel,), start_time_s=actor.current_time_s)
    assert second.total_s > 4.
    assert second.provenance['resource_recovery_decision']['selected_action_id'] is None
    assert actor.cooldown_ready_s[channel.id] == 480.


def test_paid_100_mob_objective_reuses_channel_only_after_cooldown():
    from src.game.data.forever import build_game_ir_slice
    from src.game.model import PolicyCondition, PolicyDefinition, PolicyRuleDefinition
    from src.game.multi_pull import evaluate_repeated_pulls

    ir = build_game_ir_slice(class_key='mage', level=30)
    bolt = next(a for a in ir.actions if a.family_key == 'frostbolt')
    channel = next(a for a in ir.actions if a.family_key == 'evocation')
    policy = PolicyDefinition(id='wf378:paid100', label='Frostbolt without in-combat channel',
        rules=(PolicyRuleDefinition('bolt', bolt.id, conditions=(
            PolicyCondition(kind='resource_threshold', resource_id='mana', operator='gte', value=100.),)),))
    args = dict(ir_slice=ir, policy=policy, level=30, target_health=150., count=100,
                pack_size=1, schedule_incoming_attacks=False,
                recovery_mode='always', max_actions=150)
    water = evaluate_repeated_pulls(**args, recovery_action_ids=())
    channel_enabled = evaluate_repeated_pulls(**args)
    assert len(water.pulls) == len(channel_enabled.pulls) == 100
    assert all(p['pack_all_defeated'] for p in channel_enabled.pulls)
    assert channel_enabled.seconds_per_mob < water.seconds_per_mob
    assert channel_enabled.actor.cooldown_ready_s[channel.id] >= 480.
    assert channel_enabled.actor.current_time_s >= 480.
