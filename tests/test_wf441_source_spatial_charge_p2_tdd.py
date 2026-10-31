"""Feral Charge Bear+Cat source-granted actions and real 2D movement."""
from pathlib import Path
import json,shutil
import pytest
from src.game.data.forever.registry import build_game_ir_slice
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection
from src.game.runtime import ActorState,CombatRuntime,TargetState
from src.game.model import SpatialChargeEffect,ControlEffect
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
from tools.wf441_ingest_spatial_charge import ingest
ROOT=Path(__file__).resolve().parents[1];DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'
OBS=ROOT/'evidence/wf441/SOURCE_SPATIAL_CHARGE_INDEX.json'
FILL={'ferocity':5,'heart_of_the_wild':5,'feral_charge':1}

def chosen():
    raw=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    c=compile_talent_runtime(raw)[0]
    ir=apply_talent_selection(c,FILL,level=30,bonus_talent_points=5)[0]
    bear=next(a for a in ir.actions if a.id=='feral_charge:bear')
    cat=next(a for a in ir.actions if a.id=='feral_charge:cat')
    return raw,c,ir,bear,cat

def runtime(ir,mode):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode(mode)
    actor.resources['rage']=60.
    targets=[TargetState.with_health('m0',10000.),TargetState.with_health('m1',10000.)]
    rt=CombatRuntime(actor=actor,target=targets[0],other_targets=tuple(targets[1:]),
        spatial_positions_yards={'m0':(15.,0.),'m1':(30.,0.)},
        melee_radius_yards=5.,aggro_radius_yards=10.)
    return rt

def test_source_granted_two_forms_different_cooldowns():
    raw,c,ir,bear,cat=chosen()
    assert not any(a.family_key=='feral_charge' for a in raw.actions)
    assert [m.kind for m in next(t for t in c.talents if t.id=='feral_charge').ranks[0].modifiers]==['grant_source_spatial_charge_actions']
    assert bear.cooldown_s==15 and cat.cooldown_s==30
    assert bear.costs[0].resource_id=='rage' and bear.costs[0].amount==5
    assert len([e for e in bear.effects if isinstance(e,ControlEffect)])==1
    assert not any(isinstance(e,ControlEffect) for e in cat.effects)
    assert isinstance(cat.effects[0],SpatialChargeEffect)
    assert bear.id in next(m.enabled_action_ids for m in ir.modes if m.id=='bear')
    assert cat.id in next(m.enabled_action_ids for m in ir.modes if m.id=='cat')


def test_bear_2d_charge_repositions_and_roots_real_target():
    _,_,ir,bear,_=chosen();rt=runtime(ir,'bear')
    assert rt.spatial_action_in_range(bear)
    rt.schedule_action(bear)
    assert rt.actor.resources['rage']==55.
    assert rt.actor.cooldown_ready_s[bear.id]==15.
    assert rt.player_position_yards[0]==pytest.approx(13.5)
    assert rt.targets['m0'].active_controls['root']==pytest.approx(4.)
    assert any(x.kind=='SpatialChargeArrival' for x in rt.trace)
    rt.advance_to(4.01)
    assert rt.targets['m0'].active_controls.get('root',0)<4.01


def test_cat_2d_charge_leaps_behind_but_does_not_root():
    _,_,ir,_,cat=chosen();rt=runtime(ir,'cat')
    rt.schedule_action(cat)
    assert rt.player_position_yards[0]==pytest.approx(16.5)
    assert rt.target.metadata['attacker_relative_position']=='behind'
    assert 'root' not in rt.target.active_controls
    assert rt.actor.cooldown_ready_s[cat.id]==30.


def test_out_of_range_fails_before_cost_and_solo_geometry_fails_closed():
    _,_,ir,bear,cat=chosen();rt=runtime(ir,'bear')
    rt.select_target('m1');before=rt.actor.resources['rage']
    with pytest.raises(ValueError,match='OUT_OF_RANGE'):rt.schedule_action(bear)
    assert rt.actor.resources['rage']==before
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    actor.transition_mode('bear');actor.resources['rage']=10
    solo=CombatRuntime(actor=actor,target=TargetState.with_health('m0',1000.))
    with pytest.raises(ValueError,match='REQUIRES_2D'):solo.schedule_action(bear)
    assert actor.resources['rage']==10


def test_cooldown_persists_and_source_tamper_fails(tmp_path):
    _,_,ir,bear,_=chosen();rt=runtime(ir,'bear')
    rt.schedule_action(bear)
    rt.advance_to(1.5)
    with pytest.raises(ValueError,match='cooldown|ready'):
        rt.schedule_action(bear)
    db=tmp_path/'staged.sqlite';shutil.copy2(DB,db)
    assert ingest(db,OBS)==1 and ingest(db,OBS)==1
    p=json.loads(OBS.read_text());p['records'][0]['forms'][1]['cooldown_s']=14.
    altered=tmp_path/'bad.json';altered.write_text(json.dumps(p))
    with pytest.raises(ValueError,match='CONFLICT'):ingest(db,altered)


def test_p2_rank_reduced_but_qualified_partial():
    raw,_,_,_,_=chosen()
    audit=audit_checkpoint_p2_executor(raw,db_path=DB,
        checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),bonus_talent_points=5)
    assert audit['reachable_without_executor']==2
    row=next(t for t in audit['structural_witnesses'] if t['talent_id']=='feral_charge')
    assert row['application']['status']=='APPLIED_IN_GAME_IR'
    assert 'ENEMY_CAST_INTERRUPT_NOT_RUNTIME_CERTIFIED' in row['partial_semantics']
    assert not audit['green']
