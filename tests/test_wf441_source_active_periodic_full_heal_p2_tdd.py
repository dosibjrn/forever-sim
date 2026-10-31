"""Source-authoritative Forever Swiftmend: L30 real execution, no HOT consumption."""
from pathlib import Path
import json, sqlite3, shutil
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.game.runtime.simulator import ActionNotEligibleError, expected_periodic_tick_heal,_periodic_tick_count
from src.game.model.ir import ActivePeriodicFullHealEffect,PeriodicHealEffect
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
from tools.wf441_ingest_active_periodic_heal import ingest
ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
OBS=ROOT/'evidence/wf441/SOURCE_ACTIVE_PERIODIC_HEAL_INDEX.json'
FILL={'furor':5,'natural_shapeshifter':3,'naturalist':2,'natures_focus':5,'swiftmend':1}

def chosen(db=DB):
    raw=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
    compiled=compile_talent_runtime(raw)[0]
    applied=apply_talent_selection(compiled,FILL,level=30,bonus_talent_points=5)[0]
    button=next(a for a in applied.actions if a.family_key=='swiftmend')
    rejuvenation=next(a for a in applied.actions if a.family_key=='rejuvenation')
    return raw,compiled,applied,button,rejuvenation

def runtime(ir):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resources['mana']=3000.;actor.resource_capacity['mana']=3000.
    actor.resources['health']=100.;actor.resource_capacity['health']=3000.
    actor.resource_regeneration_per_s['health']=0.
    return CombatRuntime(actor=actor,target=TargetState.with_health('dummy',100000.))

def test_real_talent_selected_and_source_typed_button():
    raw,compiled,ir,button,hot=chosen()
    assert not any(a.family_key=='swiftmend' for a in raw.actions)
    talent=next(t for t in compiled.talents if t.id=='swiftmend')
    assert [m.kind for m in talent.ranks[0].modifiers]==['grant_source_active_periodic_full_heal']
    assert button.costs[0].amount==pytest.approx(122.8)
    assert button.cooldown_s==15. and button.cast_time_s==0.
    assert any(isinstance(e,ActivePeriodicFullHealEffect) for e in button.effects)
    assert 'aura_any_present' in {r['kind'] for r in button.requirements}
    assert button.id in next(m.enabled_action_ids for m in ir.modes if m.id=='caster')
    assert button.metadata['source_hot_preserved'] is True
    assert button.metadata['source_multiple_hot_priority']=='UNVERIFIED'

def test_no_hot_fails_before_spending_and_full_duration_heal_preserves_ticks():
    _,_,ir,button,hot=chosen();rt=runtime(ir)
    initial_mana=rt.actor.resources['mana']
    with pytest.raises(ActionNotEligibleError): rt.enqueue_action(button)
    assert rt.actor.resources['mana']==initial_mana
    assert not rt.actor.cooldown_ready_s.get(button.id,0)
    rt.schedule_action(hot);rt.advance_to(0.)
    aura_id=next(e.aura_id for e in hot.effects if isinstance(e,PeriodicHealEffect))
    assert aura_id in rt.actor.active_auras
    hot_generation=rt.actor.active_auras[aura_id].generation
    rt.advance_to(1.5)
    health_before=rt.actor.resources['health']
    rt.enqueue_action(button);rt.advance_to(1.5)
    heals=[e for e in rt.trace if e.kind=='Heal' and e.action_id==button.id]
    assert len(heals)==1
    effect=next(e for e in hot.effects if isinstance(e,PeriodicHealEffect))
    expect=expected_periodic_tick_heal(effect,healing_power=rt.actor.effective_healing_power(rt.spell_power))*_periodic_tick_count(effect)
    assert heals[0].payload['amount']==pytest.approx(expect)
    assert rt.actor.resources['health']==pytest.approx(min(3000,health_before+expect))
    assert rt.actor.cooldown_ready_s[button.id]==pytest.approx(16.5)
    assert rt.actor.active_auras[aura_id].generation==hot_generation
    assert any(e.kind=='PeriodicTick' and e.payload.get('aura_id')==aura_id for e in rt.trace if e.time_s<=1.5) is False
    rt.advance_to(3.01)
    assert any(e.kind=='PeriodicTick' and e.payload.get('aura_id')==aura_id for e in rt.trace)

def test_instant_heal_matches_whole_duration_not_remaining_at_end():
    _,_,ir,button,hot=chosen();rt=runtime(ir)
    rt.schedule_action(hot);rt.advance_to(0.)
    aura_id=next(e.aura_id for e in hot.effects if isinstance(e,PeriodicHealEffect))
    rt.advance_to(9.)
    if rt.actor.resources['health']>2000: rt.actor.resources['health']=100.
    rt.enqueue_action(button);rt.advance_to(9.)
    event=next(e for e in rt.trace if e.kind=='Heal' and e.action_id==button.id)
    effect=next(e for e in hot.effects if isinstance(e,PeriodicHealEffect))
    expected=expected_periodic_tick_heal(effect,healing_power=rt.actor.effective_healing_power(rt.spell_power))*_periodic_tick_count(effect)
    assert event.payload['amount']==pytest.approx(expected)
    assert aura_id in rt.actor.active_auras

def test_source_ingest_idempotent_tamper_fails(tmp_path):
    db=tmp_path/'staged.sqlite';shutil.copy2(DB,db)
    assert ingest(db,OBS)==1 and ingest(db,OBS)==1
    payload=json.loads(OBS.read_text());payload['records'][0]['source_hot_consumption']=True
    corrupted=tmp_path/'bad.json';corrupted.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='CONFLICT'):ingest(db,corrupted)

def test_p2_missing_executor_count_decreases_but_source_semantics_red():
    raw,_,_,_,_=chosen()
    r=audit_checkpoint_p2_executor(raw,db_path=DB,
      checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),bonus_talent_points=5)
    assert r['reachable_without_executor']==2
    rank=next(x for x in r['structural_witnesses'] if x['talent_id']=='swiftmend')
    assert rank['application']['status']=='APPLIED_IN_GAME_IR'
    assert 'MULTIPLE_ACTIVE_HOT_SELECTION_NOT_SOURCE_VERIFIED' in rank['partial_semantics']
    assert not r['green']

def test_regrowth_periodic_component_is_legal_hot_source_and_not_consumed():
    _,_,ir,button,rejuv=chosen()
    regrowth=max((a for a in ir.actions if a.family_key=='regrowth'),
                 key=lambda a:float(a.costs[0].amount))
    rt=runtime(ir)
    rt.schedule_action(regrowth)
    aura_id=next(e.aura_id for e in regrowth.effects if isinstance(e,PeriodicHealEffect))
    assert aura_id in rt.actor.active_auras
    rt.advance_to(max(rt.actor.gcd_ready_s,rt.actor.current_time_s))
    rt.schedule_action(button)
    heals=[e for e in rt.trace if e.kind=='Heal' and e.action_id==button.id]
    assert len(heals)==1 and heals[0].payload['source_family']=='regrowth'
    assert aura_id in rt.actor.active_auras
    assert rt.actor.active_auras[aura_id].source_action_id==regrowth.id
