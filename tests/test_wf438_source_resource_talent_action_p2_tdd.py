"""WF438 P2 RED -> mechanics GREEN -> gate still RED: source resource conversion.

The historical-version mechanics are deliberately uncertified for pinned 70338.
"""
from pathlib import Path
from dataclasses import replace
import json,sqlite3,shutil
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.data.forever.source_rank_promotion import promote_atomic_source_talent_effects
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.game.runtime.simulator import action_eligibility
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
from tools.wf438_ingest_resource_actions import ingest

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
OBS=ROOT/'evidence/wf438/SOURCE_RESOURCE_ACTIONS.json'
FILL={'ferocity':5,'heart_of_the_wild':5,'shredding_attacks':3,
      'feral_instinct':3,'thick_hide':3,'shifting_power':1}

def compiled(db=DB):
    return compile_talent_runtime(build_game_ir_slice(class_key='druid',level=30,ability_db_path=db))[0]

def selection(extra):
    return apply_talent_selection(compiled(),{**FILL,'improved_shifting_power':extra},
                                  level=30,bonus_talent_points=5)[0]

def button(ir):
    return next(a for a in ir.actions if a.family_key=='shifting_power')

def state(ir,*,energy=20.,mana=1000.):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('cat')
    actor.resources['energy']=energy
    actor.resource_regeneration_per_s['energy']=0.
    actor.resource_regeneration_per_s['mana']=0.
    actor.resources['mana']=mana
    actor.resource_capacity['mana']=max(1000.,mana)
    return actor


def test_source_rank_grant_and_two_cooldown_ranks_are_real_modifiers():
    ir=compiled()
    base=next(t for t in ir.talents if t.id=='shifting_power')
    improved=next(t for t in ir.talents if t.id=='improved_shifting_power')
    assert [m.kind for m in base.ranks[0].modifiers]==['grant_source_resource_action']
    assert [r.modifiers[0].value for r in improved.ranks]==[-4.,-8.]
    assert base.ranks[0].modifiers[0].provenance['unsupported_build_bridge']
    for rank in improved.ranks:
        assert rank.modifiers[0].provenance['source_build']=='1.60.1.70338'


def test_real_granted_button_only_after_talent_selection_and_cooldown_rank():
    raw=compiled()
    assert not any(a.family_key=='shifting_power' for a in raw.actions)
    for rank,seconds in ((0,16.),(1,12.),(2,8.)):
        ir=selection(rank)
        a=button(ir)
        assert a.cooldown_s==pytest.approx(seconds)
        assert a.costs[0].amount==pytest.approx(614.*.55)
        assert a.effects[0].amount==40.
        assert a.id in next(m.enabled_action_ids for m in ir.modes if m.id=='cat')
        assert a.id not in next(m.enabled_action_ids for m in ir.modes if m.id=='bear')


def test_real_combat_runtime_resource_cost_cap_and_cooldown():
    for rank,seconds in ((0,16.),(1,12.),(2,8.)):
        ir=selection(rank);a=button(ir)
        actor=state(ir,energy=30.,mana=1000.)
        rt=CombatRuntime(actor=actor,target=TargetState.with_health('dummy',1000.))
        assert action_eligibility(action=a,actor=actor,target=rt.target).eligible
        rt.schedule_action(a)
        rt.advance_to(1.5)
        assert actor.resources['energy']==pytest.approx(70.)
        assert actor.resources['mana']==pytest.approx(1000.-614.*.55)
        assert not action_eligibility(action=a,actor=actor,target=rt.target).eligible
        rt.advance_to(seconds)
        assert action_eligibility(action=a,actor=actor,target=rt.target).eligible
        rt.schedule_action(a)
        rt.advance_to(seconds+1.5)
        assert actor.resources['energy']==pytest.approx(100.)
        assert actor.resources['mana']==pytest.approx(1000.-2*614.*.55)
        assert not action_eligibility(action=a,actor=actor,target=rt.target).eligible


def test_no_cast_at_max_energy_outside_mode_or_without_mana():
    ir=selection(2);a=button(ir)
    at_max=state(ir,energy=100.)
    assert not action_eligibility(action=a,actor=at_max).eligible
    wrong_mode=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    assert not action_eligibility(action=a,actor=wrong_mode).eligible
    low_mana=state(ir,energy=20.,mana=0.)
    assert not action_eligibility(action=a,actor=low_mana).eligible


def test_source_sqlite_values_drive_action_without_constants_in_executor(tmp_path):
    db=tmp_path/'staged.sqlite';shutil.copy2(DB,db)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE sourced_talent_resource_action_facts SET resource_gain=45 WHERE talent_id=?',('shifting_power',))
    # An altered source action fact must NOT pass the immutable pinned talent rank value.
    broken=compiled(db)
    talent=next(t for t in broken.talents if t.id=='shifting_power')
    assert not talent.ranks[0].modifiers
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE sourced_talent_resource_action_facts SET resource_gain=40,cooldown_s=19 WHERE talent_id=?',('shifting_power',))
    changed=compiled(db)
    applied,_=apply_talent_selection(changed,FILL,level=30,bonus_talent_points=5)
    assert button(applied).cooldown_s==pytest.approx(19.)


def test_wrong_version_fact_and_false_certification_fail_closed(tmp_path):
    db=tmp_path/'staged.sqlite';shutil.copy2(DB,db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE sourced_talent_resource_action_facts SET source_build='1.60.1.70000'")
    rank=next(t for t in compiled(db).talents if t.id=='shifting_power').ranks[0]
    assert not rank.modifiers
    payload=json.loads(OBS.read_text());payload['records'][0]['bridge_verified']=1
    source=tmp_path/'bad.json';source.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='UNVERIFIED_SOURCE_RESOURCE_ACTION_BRIDGE'):
        ingest(db,source)


def test_source_partial_runtime_qualifier_preserved_by_strict_gate():
    ir=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    report=audit_checkpoint_p2_executor(ir,db_path=DB,
          checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),bonus_talent_points=5)
    for talent_id,rank in (('shifting_power',1),('improved_shifting_power',1),('improved_shifting_power',2)):
        witness=next(r for r in report['structural_witnesses'] if r['talent_id']==talent_id and r['rank']==rank)
        assert witness['application']['status']=='APPLIED_IN_GAME_IR',witness
    assert not report['green']
    assert report['reachable_without_executor'] <= 10


def test_actual_paid_100_mob_policy_executes_source_resource_button_not_only_ir():
    from src.game.multi_pull import evaluate_repeated_pulls
    from src.game.model import PolicyDefinition,PolicyRuleDefinition,PolicyCondition
    ir=selection(2)
    ability=button(ir)
    claw=next(a for a in ir.actions if a.id=='claw:28')
    enter=next(a for a in ir.actions if a.family_key=='cat_form')
    exit_action=next(a for a in ir.actions if a.id=='cancel_mode:cat')
    policy=PolicyDefinition('source_shifting_power_100mob','resource conversion plus claw',
        rules=(PolicyRuleDefinition('use_source_resource',ability.id,
            conditions=(PolicyCondition(kind='resource_threshold',resource_id='energy',
                operator='lt',value=65.),)),
               PolicyRuleDefinition('claw',claw.id)))
    run=evaluate_repeated_pulls(ir_slice=ir,policy=policy,level=30,target_health=180.,
        count=100,schedule_incoming_attacks=True,pre_combat_action_ids=(enter.id,),
        post_combat_action_ids=(exit_action.id,),recovery_mode='always',max_actions=128)
    assert len(run.pulls)==100
    assert all(p['pack_all_defeated'] for p in run.pulls)
    assert sum(any(a['action_id']==ability.id for a in p['selected_actions'])
               for p in run.pulls)>0
    assert run.seconds_per_mob>0


def test_shapeshift_cost_reducers_apply_to_sourced_resource_action():
    # Source tooltip explicitly says existing shapeshifting cost reductions
    # also apply to the granted energy-conversion button. The generic
    # resource_cost_reduction_group implements it without talent-ID branches.
    ir=compiled()
    vanilla=apply_talent_selection(ir,FILL,level=30,bonus_talent_points=5)[0]
    with_cost_reducer={**FILL,'thick_hide':1,'natures_focus':5,
                       'natural_shapeshifter':3}
    assert sum(with_cost_reducer.values())==26
    cheaper=apply_talent_selection(ir,with_cost_reducer,level=30,bonus_talent_points=5)[0]
    assert button(cheaper).costs[0].amount==pytest.approx(button(vanilla).costs[0].amount*.7)
    assert button(cheaper).effects==button(vanilla).effects
