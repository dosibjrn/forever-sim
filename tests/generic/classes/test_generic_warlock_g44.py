import pytest
from src.game.data.forever import build_game_ir_slice
from src.game.runtime.state import ActorState, TargetState
from src.game.runtime.simulator import CombatRuntime, ActionNotEligibleError


def _runtime(level=14, health=400, mana=120, mob=200):
    ir = build_game_ir_slice(class_key='warlock', level=level)
    actor = ActorState.from_ir(ir.actor, ir.resources)
    actor.resources.update(health=float(health), mana=float(mana))
    return ir, actor, CombatRuntime(actor=actor, target=TargetState.with_health('mob', mob))


def test_tap_is_real_health_to_mana_with_cap_and_safety():
    ir, actor, rt = _runtime(mana=75, health=90)
    tap = next(a for a in ir.actions if a.family_key == 'life_tap')
    rt.schedule_action(tap)
    assert actor.resources['health'] == 60
    assert actor.resources['mana'] == 105
    actor.resources['health'] = 40
    with pytest.raises(ActionNotEligibleError):
        rt.schedule_action(tap, at_time_s=2.)


def test_channel_ticks_during_cast_and_heals_from_actual_damage():
    ir, actor, rt = _runtime(health=200, mana=200, mob=100)
    drain = next(a for a in ir.actions if a.family_key == 'drain_life')
    bolt = next(a for a in ir.actions if a.family_key == 'shadow_bolt')
    rt.enqueue_action(drain)
    rt.advance_to(2.)
    assert rt.total_damage == pytest.approx(20.)
    assert actor.resources['health'] == pytest.approx(220.)
    with pytest.raises(ActionNotEligibleError):
        rt.enqueue_action(bolt)
    rt.advance_to(5.)
    assert rt.total_damage == pytest.approx(50.)
    assert actor.resources['health'] == pytest.approx(250.)
    assert len([e for e in rt.trace if e.kind == 'Damage' and e.action_id == drain.id]) == 5


def test_channel_overkill_heal_capped_and_lvl_gate():
    ir, actor, rt = _runtime(health=200, mana=200, mob=3)
    drain = next(a for a in ir.actions if a.family_key == 'drain_life')
    rt.schedule_action(drain)
    assert actor.resources['health'] == pytest.approx(203.)
    assert build_game_ir_slice(class_key='warlock', level=12)
    assert all(a.family_key != 'drain_life' for a in build_game_ir_slice(class_key='warlock',level=12).actions)
