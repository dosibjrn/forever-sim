"""Evocation: source-based OOC spirit ticks during combat and interrupt-at-full."""
from dataclasses import replace
import pytest
from src.game.data.forever.mage import build_source_slice
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.model import ActionDefinition, DamageEffect


def _setup(*, spirit=60., mana=0., capacity=750.):
    ir=build_source_slice(30)
    evo=next(a for a in ir.actions if a.family_key=='evocation')
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.stats['spirit']=spirit
    actor.resources['mana']=mana
    actor.resource_regeneration_per_s['mana']=0.  # isolate the channel from ordinary passive regen
    actor.resource_capacity['mana']=capacity
    return actor,evo,CombatRuntime(actor=actor,target=TargetState.with_health('mob',200.))


def test_evo_uses_spirit_and_2s_ticks_not_hardcoded_48_per_s():
    actor,evo,rt=_setup(spirit=60.,capacity=3000.)
    assert evo.effects[0].tick_interval_s == 2.
    rt.enqueue_action(evo)
    rt.advance_to(1.9)
    assert actor.resource_amount('mana') == pytest.approx(0.)
    rt.advance_to(2.)
    assert actor.resource_amount('mana') == pytest.approx(16.*(12.5+60./4.))
    rt.advance_to(4.)
    assert actor.resource_amount('mana') == pytest.approx(2.*16.*(12.5+60./4.))


def test_evo_ends_channel_at_full_at_4s_not_forced_8s():
    actor,evo,rt=_setup(spirit=60.,capacity=750.)
    ended=rt.schedule_action(evo)
    assert ended == pytest.approx(4.)
    assert actor.current_time_s == pytest.approx(4.)
    assert actor.resource_amount('mana') == pytest.approx(750.)
    assert actor.cooldown_ready_s[evo.id] == pytest.approx(480.)
    assert any(e.kind=='ChannelStopped' for e in rt.trace)


def test_spirit_affects_regen_and_channel_continues_if_still_missing():
    actor,evo,rt=_setup(spirit=20.,capacity=3000.)
    rt.schedule_action(evo)
    assert actor.current_time_s == pytest.approx(8.)
    assert actor.resource_amount('mana') == pytest.approx(4.*16.*(12.5+20./4.))


def test_channel_break_clears_cast_busy_and_no_stale_completion():
    actor,evo,rt=_setup(spirit=60.,capacity=750.)
    rt.schedule_action(evo)
    # The next legal action can start directly after the tick that filled mana.
    bolt=ActionDefinition(id='wf377:test_bolt',family_key='probe',name='Probe',
        owner_actor_id=actor.id,requirements=(),costs=(),cast_time_s=0.,gcd_s=0.,cooldown_s=0.,
        effects=(DamageEffect('damage','arcane','enemy',5.,5.),),
        provenance=({'authority':'synthetic_test'},))
    rt.schedule_action(bolt)
    assert rt.target.health==pytest.approx(195.)
    assert actor.current_time_s==pytest.approx(4.)
