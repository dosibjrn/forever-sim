from dataclasses import replace
from pathlib import Path
from src.game.data.forever import build_game_ir_slice
from src.game.model import SummonEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.v2.generic_backend import _policy_combat_evaluation
from src.version import SOFTWARE_VERSION


def make_runtime(level=20):
    ir=build_game_ir_slice(class_key='shaman',level=level)
    runtime=CombatRuntime(actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes),
        target=TargetState.with_health('durable', 100000),
        companions=tuple(ActorState.from_ir(d,()) for d in ir.companions),
        timed_summons=ir.timed_summons,auto_attacks=ir.auto_attacks)
    return ir,runtime


def test_source_and_generic_ir():
    assert SOFTWARE_VERSION=='0.11.48.158'
    ir=build_game_ir_slice(class_key='shaman',level=10)
    action=next(a for a in ir.actions if a.family_key=='searing_totem')
    assert action.costs[0].amount==25 and action.gcd_s==1
    assert isinstance(action.effects[0],SummonEffect)
    assert ir.timed_summons[0].duration_s==30
    assert ir.auto_attacks[-1].school=='fire'
    assert ir.companions[0].id==ir.timed_summons[0].summoned_actor_id
    assert 'companions' in ir.as_dict() and 'timed_summons' in ir.as_dict()


def test_summon_through_action_cost_damage_lifetime():
    ir,r=make_runtime()
    action=next(a for a in ir.actions if a.family_key=='searing_totem')
    mana_before=r.actor.resource_amount('mana')
    r.enqueue_action(action)
    r.advance_to(29.99)
    events=r.result().events
    assert sum(e.kind=='SummonSpawn' for e in events)==1
    assert any(e.kind=='ActionStarted' and e.payload.get('resource_spend') for e in events)
    hits=[e for e in events if e.kind=='Damage' and e.actor_id=='shaman:searing_totem' and e.payload.get('applied')]
    assert len(hits)==14 and all(e.payload['amount']==10 for e in hits)
    r.advance_to(34)
    assert sum(e.kind=='SummonDespawn' for e in r.result().events)==1
    assert not [e for e in r.result().events if e.kind=='Damage' and e.actor_id=='shaman:searing_totem' and e.time_s>30]
    assert r.result().damage_by_actor['shaman:searing_totem']==140


def test_generic_shaman_normal_evaluation_executes_totem():
    ir=build_game_ir_slice(class_key='shaman',level=20)
    ev, ex, _=_policy_combat_evaluation(ir,level=20)
    assert ev is not None and ex.timeline.target_defeated
    assert any(a['action_id']=='searing_totem:3599' for a in ex.selected_actions)
    assert ex.timeline.damage_by_actor['shaman:searing_totem']>0
    assert any(e.kind=='SummonSpawn' for e in ex.timeline.events)
    engine=(Path('src/game/runtime/simulator.py').read_text()+Path('src/game/policy.py').read_text()).lower()
    assert 'shaman' not in engine


def test_class_neutral_generic_summon_action():
    ir,r=make_runtime()
    summon=next(a for a in ir.actions if a.family_key=='searing_totem')
    alternate=replace(summon,id='generic:arbitrary_emitter',name='Arbitrary emitter')
    r.enqueue_action(alternate)
    r.advance_to(3.)
    assert r.result().damage_by_actor.get('shaman:searing_totem',0)>0
