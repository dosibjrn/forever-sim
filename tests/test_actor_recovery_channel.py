"""Preserve generic actor recovery's mana-channel choice and cooldown behavior."""
from src.game.data.forever.mage import build_source_slice
from src.game.recovery import recover_actor_to_full
from src.game.runtime import ActorState


def _setup():
    ir = build_source_slice(30)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.stats["spirit"] = 60.0
    actor.resources["mana"] = 0.0
    actor.resource_capacity["mana"] = 750.0
    actor.resources["health"] = actor.resource_capacity["health"]
    return actor, next(action for action in ir.actions if action.family_key == "evocation")


def test_spirit_channel_competes_with_vendor_water_and_persists_cooldown():
    plain, _ = _setup()
    water = recover_actor_to_full(actor=plain, level=30, actions=(), start_time_s=0.0)
    actor, channel = _setup()
    result = recover_actor_to_full(actor=actor, level=30, actions=(channel,), start_time_s=0.0)
    assert result.total_s < water.total_s
    assert result.total_s == 4.0
    assert actor.resource_amount("mana") == 750.0
    assert actor.cooldown_ready_s[channel.id] == 480.0
    assert result.provenance["resource_recovery_decision"]["selected_action_id"] == channel.id
    actor.resources["mana"] = 0.0
    second = recover_actor_to_full(actor=actor, level=30, actions=(channel,), start_time_s=actor.current_time_s)
    assert second.total_s > 4.0
    assert second.provenance["resource_recovery_decision"]["selected_action_id"] is None
    assert actor.cooldown_ready_s[channel.id] == 480.0
