"""WF440: RED->mechanics GREEN; P2 gate remains RED for source version/other ranks."""
from pathlib import Path
from dataclasses import replace
import json,sqlite3,shutil
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.game.runtime.simulator import ActionNotEligibleError
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
from tools.wf440_ingest_next_cast_instant import ingest

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
OBS=ROOT/'evidence/wf440/SOURCE_NEXT_CAST_INSTANT_INDEX.json'
FILL={'furor':5,'natural_shapeshifter':3,'naturalist':5,'natures_focus':5,
      'natures_swiftness':1,'subtlety':2}

def ir_slice(db=DB):
    base=build_game_ir_slice(class_key='druid',level=30,ability_db_path=db)
    compiled=compile_talent_runtime(base)[0]
    return compiled

def chosen(db=DB):
    return apply_talent_selection(ir_slice(db),FILL,level=30,bonus_talent_points=5)[0]

def actions(ir):
    return (next(a for a in ir.actions if a.family_key=='natures_swiftness'),
            next(a for a in ir.actions if a.id=='wrath:5180'),
            next(a for a in ir.actions if a.family_key=='moonfire' and a.id=='moonfire:8927'))

def runtime(ir):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.resources['mana']=3000.;actor.resource_capacity['mana']=3000.;actor.resource_regeneration_per_s['mana']=0.
    return CombatRuntime(actor=actor,target=TargetState.with_health('dummy',100000.))

def test_source_pinned_rank_and_real_granted_button_no_class_branch():
    base=ir_slice(); talent=next(t for t in base.talents if t.id=='natures_swiftness')
    assert [m.kind for m in talent.ranks[0].modifiers]==['grant_source_next_cast_instant_action']
    assert talent.ranks[0].modifiers[0].provenance['unsupported_build_bridge']
    assert not any(a.family_key=='natures_swiftness' for a in base.actions)
    ir=chosen();button,wrath,moon=actions(ir)
    assert button.cooldown_s==180. and button.gcd_s==0. and not button.costs
    assert not button.effects
    assert button.id in next(m.enabled_action_ids for m in ir.modes if m.id=='caster')


def test_runtime_next_nature_cast_consumes_exactly_one_charge_and_cooldown_persists():
    ir=chosen();button,wrath,moon=actions(ir); rt=runtime(ir)
    assert rt.actor.current_mode_id=='caster'
    rt.schedule_action(button);rt.advance_to(0.)
    assert rt.actor.gcd_ready_s==pytest.approx(0.)
    assert rt.actor.cooldown_ready_s[button.id]==pytest.approx(180.)
    assert rt.actor.source_next_cast_instant_charges=={'nature':1}
    with pytest.raises(ActionNotEligibleError):rt.enqueue_action(button)
    rt.schedule_action(wrath);rt.advance_to(0.)
    start=[e for e in rt.trace if e.kind=='ActionStarted' and e.action_id==wrath.id][-1]
    assert start.payload['cast_time_s']==pytest.approx(0.)
    assert rt.actor.source_next_cast_instant_charges=={'nature':0}
    assert any(e.kind=='NextCastInstantConsumed' for e in rt.trace)
    rt.advance_to(1.5);rt.enqueue_action(wrath);rt.advance_to(1.5)
    start=[e for e in rt.trace if e.kind=='ActionStarted' and e.action_id==wrath.id][-1]
    assert start.payload['cast_time_s']==pytest.approx(wrath.cast_time_s)
    assert rt.actor.cooldown_ready_s[button.id]==pytest.approx(180.)


def test_failed_cast_and_other_school_do_not_consume_bank():
    ir=chosen();button,wrath,moon=actions(ir);rt=runtime(ir)
    rt.schedule_action(button);rt.advance_to(0.)
    other=moon
    assert any(getattr(e,'school',None)=='arcane' for e in other.effects)
    rt.enqueue_action(other);rt.advance_to(0.)
    assert rt.actor.source_next_cast_instant_charges['nature']==1
    with pytest.raises(ActionNotEligibleError):rt.enqueue_action(wrath,at_time_s=0.)
    assert rt.actor.source_next_cast_instant_charges['nature']==1
    rt.advance_to(2.);rt.enqueue_action(wrath);rt.advance_to(2.)
    assert rt.actor.source_next_cast_instant_charges['nature']==0


def test_off_gcd_activation_during_existing_gcd_does_not_shorten_gcd():
    ir=chosen();button,wrath,moon=actions(ir);rt=runtime(ir)
    rt.schedule_action(moon)
    assert rt.actor.gcd_ready_s==pytest.approx(1.5)
    rt.schedule_action(button)
    assert rt.actor.source_next_cast_instant_charges['nature']==1
    assert rt.actor.gcd_ready_s==pytest.approx(1.5)
    rt.enqueue_action(wrath,at_time_s=1.5);rt.advance_to(1.5)
    start=[e for e in rt.trace if e.kind=='ActionStarted' and e.action_id==wrath.id][-1]
    assert start.payload['cast_time_s']==pytest.approx(0.)


def test_source_reingest_idempotent_and_wrong_source_hash_fails(tmp_path):
    db=tmp_path/'talents.sqlite';shutil.copy2(DB,db)
    assert ingest(db,OBS)==1 and ingest(db,OBS)==1
    with sqlite3.connect(db) as con:
        count=con.execute('select count(*) from sourced_talent_next_cast_action_facts').fetchone()[0]
    assert count==1
    source=json.loads(OBS.read_text());source['records'][0]['indexed_payload_sha256']='0'*64
    altered=tmp_path/'false.json';altered.write_text(json.dumps(source))
    with pytest.raises(ValueError,match='INVALID_OR_UNVERIFIED'):
        ingest(db,altered)


def test_cross_build_not_certain_and_gate_fail_closed():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    r=audit_checkpoint_p2_executor(ir,db_path=DB,
        checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),bonus_talent_points=5)
    t=next(x for x in r['structural_witnesses'] if x['talent_id']=='natures_swiftness')
    assert t['application']['status']=='APPLIED_IN_GAME_IR'
    assert 'SOURCE_BUILD_BRIDGE_UNVERIFIED' in t['partial_semantics']
    assert r['reachable_without_executor']==2
    assert not r['green']


def test_100_mob_policy_real_button_and_wrath():
    from src.game.multi_pull import evaluate_repeated_pulls
    from src.game.model import PolicyDefinition,PolicyRuleDefinition
    ir=chosen();button,wrath,_=actions(ir)
    policy=PolicyDefinition('wf440_source_instant_mechanics','source button then damage',(
        PolicyRuleDefinition('instantly-next',button.id),
        PolicyRuleDefinition('wrath',wrath.id)))
    run=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=30,
        target_health=220.,count=100,schedule_incoming_attacks=False,
        recovery_mode='always',max_actions=64)
    assert len(run.pulls)==100 and all(p['pack_all_defeated'] for p in run.pulls)
    assert sum(any(a['action_id']==button.id for a in p['selected_actions']) for p in run.pulls)>=1
