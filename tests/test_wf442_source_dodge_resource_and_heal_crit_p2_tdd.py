"""Whole-rank P2: source -> legal 26pt allocation -> runtime resource/heal events."""
from dataclasses import replace
from pathlib import Path
import json, sqlite3
import pytest

from src.game.data.forever.registry import build_game_ir_slice
from src.game.data.forever.checkpoint_p2_execution_gate import audit_checkpoint_p2_executor
from src.game.data.forever.source_checkpoint_p2 import P2Checkpoint
from src.game.model.ir import HealEffect
from src.game.runtime import ActorState, CombatRuntime, TargetState
from src.game.runtime.simulator import expected_direct_heal, expected_incoming_attack
from src.game.talent_execution_coverage import compile_talent_runtime
from src.game.talents import apply_talent_selection, validate_talent_selection

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/forever/staged_druid_l30_talents_70338.sqlite'

def all_witnesses():
    source=build_game_ir_slice(class_key='druid',level=30,ability_db_path=DB)
    compiled=compile_talent_runtime(source)[0]
    audited=audit_checkpoint_p2_executor(source,db_path=DB,
        checkpoint=P2Checkpoint('druid',30,source_build='1.60.1.70338'),
        bonus_talent_points=5)
    return source,compiled,audited

def selected(tid):
    src,compiled,audited=all_witnesses()
    rec=next(x for x in audited['structural_witnesses'] if x['talent_id']==tid and x['rank']==1)
    selection=rec['witness']
    validate_talent_selection(compiled,selection,level=30,bonus_talent_points=5)
    chosen,receipt=apply_talent_selection(compiled,selection,level=30,bonus_talent_points=5)
    return src,chosen,receipt,rec

def battle(ir,*,mode=None):
    actor=ActorState.from_ir(ir.actor,ir.resources,ir.modes)
    if mode:actor.transition_mode(mode)
    actor.resources['health']=max(2000.,actor.resource_capacity.get('health',3000.))
    actor.resource_capacity['health']=max(3000.,actor.resource_capacity.get('health',3000.))
    return CombatRuntime(actor=actor,target=TargetState.with_health('mob',100000.),
                         incoming_attacks=ir.incoming_attacks,mitigation_rules=ir.mitigation_rules)

def test_all_129_reachable_ranks_have_executors_and_legal_26pt_builds():
    _,_,audit=all_witnesses()
    assert audit['reachable_rank_count']==129
    assert audit['reachable_without_executor']==0
    assert audit['rank_application_failure_count']==0
    assert audit['green'] is False
    assert 'SOURCE_RANK_PARTIAL_RUNTIME_SEMANTICS' in audit['remaining_gate_fail_reasons']

def test_improved_regrowth_rank1_source_70338_and_strict_prerequisite():
    src,ir,receipt,rec=selected('improved_regrowth')
    t=next(t for t in src.talents if t.id=='improved_regrowth')
    assert t.prerequisite=={'talent_id':'improved_rejuvenation','required_rank':3}
    assert t.metadata['checkpoint_source_deferred_rank_curve'] is False
    assert rec['application']['status']=='APPLIED_IN_GAME_IR'
    assert 'PREREQUISITE_REQUIRED_RANK_SOURCE_BUILD_BRIDGE_UNVERIFIED' in rec['partial_semantics']
    assert any(x['talent_id']=='improved_regrowth' and x['kind']=='heal_crit_chance_bonus'
               for x in receipt.applied_modifiers)
    with pytest.raises(ValueError,match='prerequisite'):
        validate_talent_selection(src,{**rec['witness'],'improved_rejuvenation':2},
                                  level=30,bonus_talent_points=5)

def test_regrowth_rank1_direct_heal_crit_expected_value_and_hot_unmodified():
    source,chosen,_,rec=selected('improved_regrowth')
    base_ir=apply_talent_selection(compile_talent_runtime(source)[0],
        {k:v for k,v in rec['witness'].items() if k!='improved_regrowth'},
        level=30,bonus_talent_points=5)[0]
    base=next(a for a in base_ir.actions if a.family_key=='regrowth')
    new=next(a for a in chosen.actions if a.family_key=='regrowth')
    bdirect=next(e for e in base.effects if isinstance(e,HealEffect))
    direct=next(e for e in new.effects if isinstance(e,HealEffect))
    assert direct.crit_chance_bonus==pytest.approx(.1)
    assert bdirect.crit_chance_bonus==0
    assert new.effects[1] == base.effects[1]  # No periodic crit granted.
    h=300.
    assert expected_direct_heal(direct,healing_power=h,spell_crit_chance=.2) > expected_direct_heal(
        bdirect,healing_power=h,spell_crit_chance=.2)
    assert expected_direct_heal(direct,healing_power=h,spell_crit_chance=.2)==pytest.approx(
        expected_direct_heal(bdirect,healing_power=h,spell_crit_chance=.2)*1.15)
    # No unsourced crit multiplier is applied to an unmodified base heal.
    # Exercise actual heal event, including actor's base crit and the new talent.
    rt=battle(chosen)
    rt.actor.resources['mana']=3000.;rt.actor.resource_capacity['mana']=3000.
    rt.actor.resources['health']=10.
    rt.schedule_action(new)
    rt.advance_to(float(new.cast_time_s)+.1)
    events=[e for e in rt.trace if e.kind=='Heal' and e.action_id==new.id]
    assert events and events[0].payload['critical_chance']==pytest.approx(
        max(0.,min(1.,rt.actor.stats.get('spell_crit_chance',0.)+.1)))

def test_natural_reaction_witness_grants_both_dodge_and_bear_rage_on_actual_incoming():
    src,chosen,receipt,rec=selected('natural_reaction')
    assert rec['status']=='SOURCE_RANK_PARTIAL_RUNTIME_SEMANTICS'
    assert 'SOURCE_BUILD_BRIDGE_UNVERIFIED' in rec['partial_semantics']
    assert {r['kind'] for r in receipt.applied_modifiers if r['talent_id']=='natural_reaction'} == {
        'actor_stat_flat','incoming_dodge_resource_gain'}
    without=apply_talent_selection(compile_talent_runtime(src)[0],
        {k:v for k,v in rec['witness'].items() if k!='natural_reaction'},
        level=30,bonus_talent_points=5)[0]
    assert chosen.actor.base_stats['dodge_chance']-without.actor.base_stats['dodge_chance']==pytest.approx(.01)
    rt=battle(chosen,mode='bear')
    incoming=replace(chosen.incoming_attacks[0], hit_chance=1.,raw_damage=0.,
                     mitigation_rule_id=None)
    rt.actor.resources['rage']=0.;rt.actor.resource_capacity['rage']=100.
    before=rt.actor.resource_amount('rage')
    resolved=rt.resolve_incoming_attack(incoming,mitigation_rules=())
    assert resolved['expected_dodge_count'] == pytest.approx(rt.actor.stats['dodge_chance'])
    # Source rank 1: 20% chance for 5 Rage on dodge = 1 Rage per dodge.
    expected_gain=resolved['expected_dodge_count']
    assert rt.actor.resource_amount('rage')-before == pytest.approx(expected_gain)
    assert any(e.kind=='ResourceEventGain' and e.payload.get('event_kind')=='incoming_physical_dodge'
               for e in rt.trace)

def test_dodge_proc_never_from_magic_or_caster_and_no_double_counting_dodge():
    _,ir,_,_=selected('natural_reaction')
    physical=replace(ir.incoming_attacks[0],hit_chance=1.,raw_damage=0.,mitigation_rule_id=None)
    rt=battle(ir,mode='bear');rt.actor.resources['rage']=0.
    spell=replace(physical,school='arcane')
    a=rt.resolve_incoming_attack(spell,mitigation_rules=())
    assert a['expected_dodge_count']==0.0
    assert rt.actor.resource_amount('rage')==pytest.approx(0.)
    prevented=replace(physical,metadata={**physical.metadata,'hit_chance_includes_actor_dodge':True})
    r=rt.resolve_incoming_attack(prevented,mitigation_rules=())
    assert r['expected_dodge_count']==0
    assert rt.actor.resource_amount('rage')==pytest.approx(0.)
    caster=battle(ir,mode='caster');caster.actor.resources['rage']=0.
    # Even a hypothetical active Rage resource cannot receive Bear-only proc.
    caster.resolve_incoming_attack(physical,mitigation_rules=())
    assert caster.actor.resource_amount('rage')==pytest.approx(0.)

def test_replay_hash_guarded_source_ingest_from_wf441_and_reject_tamper(tmp_path):
    import subprocess,zipfile,hashlib
    from tools.wf442_ingest_source_rank_observations import ingest
    archive=ROOT.parents[0]/'WF441_DRUID_L30_P2_SWIFTMEND_FERAL_CHARGE_RED_WIP_ON_WF440.zip'
    if not archive.exists():
        pytest.skip('WF441 parent archive not locally mounted; ingest behavior tested in packaging validation')
    with zipfile.ZipFile(archive) as z:
        pristine=z.read('data/forever/staged_druid_l30_talents_70338.sqlite')
    trial=tmp_path/'pristine.sqlite';trial.write_bytes(pristine)
    evidence=ROOT/'evidence/wf442/WF442_SOURCE_RANK_OBSERVATIONS.json'
    with sqlite3.connect(trial) as conn:
        old_hash=conn.execute('SELECT source_sha256 FROM checkpoint_talent_source_catalogue').fetchone()[0]
    assert old_hash==json.loads(evidence.read_text())['parent_source_sha256']
    new_hash=ingest(trial,evidence)
    assert new_hash==ingest(trial,evidence)
    with sqlite3.connect(trial) as conn:
        row=conn.execute('SELECT source_json,source_sha256 FROM checkpoint_talent_source_catalogue').fetchone()
    assert row[1]==new_hash and row[1]!=old_hash
    assert hashlib.sha256(row[0].encode()).hexdigest()==new_hash
    staged_hash=sqlite3.connect(DB).execute('SELECT source_sha256 FROM checkpoint_talent_source_catalogue').fetchone()[0]
    assert staged_hash==new_hash
    with sqlite3.connect(trial) as conn:
        conn.execute('UPDATE checkpoint_talent_source_catalogue SET source_json=source_json || ?',(' ',))
    with pytest.raises(ValueError,match='TAMPERED'):
        ingest(trial,evidence)
