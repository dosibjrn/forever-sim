"""True same-clock HOT, direct heal and vendor recovery acceptance cases."""
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.recovery import recover_actor_to_full
from src.game.runtime import ActorState


def _actor(class_key, level, health, mana):
    ir = build_game_ir_slice(class_key=class_key, level=level)
    actor = ActorState.from_ir(ir.actor, ir.resources, ir.modes)
    actor.resources.update({'health': float(health), 'mana': float(mana)})
    return ir, actor


def test_best_sourced_hot_is_really_selected_and_ticks_while_eating_and_drinking():
    ir, actor = _actor('druid', 20, 250, 400)
    old_id = id(actor)
    result = recover_actor_to_full(actor=actor, level=20, actions=ir.actions, start_time_s=10)
    assert id(actor) == old_id
    # WF284: sourced Regrowth rank 1 is now a legal recovery alternative.
    assert result.provenance['heal_action_sequence'] == ['source_spell:8936']
    assert result.total_s == pytest.approx(8.0)
    assert result.food_s > 0 and result.water_s > 0
    assert any(e['kind'] == 'Heal' and e['payload'].get('periodic') for e in result.heal_events)
    assert actor.resources['health'] == pytest.approx(actor.resource_capacity['health'])
    assert actor.resources['mana'] == pytest.approx(actor.resource_capacity['mana'])
    _, control = _actor('druid', 20, 250, 400)
    ordinary = recover_actor_to_full(actor=control, level=20, actions=(), start_time_s=10)
    assert result.total_s < ordinary.total_s


def test_compound_regrowth_direct_and_hot_execute_on_same_clock():
    ir, actor = _actor('druid', 20, 100, 614)
    regrowth = next(a for a in ir.actions if a.family_key == 'regrowth')
    result = recover_actor_to_full(actor=actor, level=20, actions=(regrowth,), start_time_s=0)
    assert result.provenance['heal_action_sequence'] == [regrowth.id]
    events = [e for e in result.heal_events if e['kind'] == 'Heal']
    assert any(not e['payload'].get('periodic') for e in events)
    assert any(e['payload'].get('periodic') for e in events)
    assert result.total_s < 17.3914
    assert result.total_s > regrowth.cast_time_s
    assert result.food_s > 0 and result.water_s > 0


def test_unaffordable_compound_heal_is_rejected_without_free_mana():
    ir, actor = _actor('druid', 20, 100, 10)
    regrowth = next(a for a in ir.actions if a.family_key == 'regrowth')
    result = recover_actor_to_full(actor=actor, level=20, actions=(regrowth,), start_time_s=0)
    assert result.provenance['heal_action_sequence'] == []
    assert result.heal_events == ()
    assert result.total_s > 0


def test_priest_renew_is_executable_by_same_generic_recovery():
    ir, actor = _actor('priest', 20, 250, 490)
    renew = next(a for a in ir.actions if a.family_key == 'renew')
    result = recover_actor_to_full(actor=actor, level=20, actions=(renew,), start_time_s=0)
    assert result.provenance['heal_action_sequence'] == [renew.id]
    assert any(e['kind'] == 'Heal' for e in result.heal_events)
    assert actor.resources['health'] == pytest.approx(actor.resource_capacity['health'])


def test_no_health_deficit_does_not_cast_heals_to_fix_mana():
    ir, actor = _actor('druid', 20, 500, 200)
    result = recover_actor_to_full(actor=actor, level=20, actions=ir.actions, start_time_s=0)
    assert result.provenance['heal_action_sequence'] == []
    assert result.food_s == pytest.approx(0)
    assert result.water_s > 0
